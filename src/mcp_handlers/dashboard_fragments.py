"""
Dashboard HTML Fragment Handlers

Serves HTML fragments for htmx-powered dashboard updates.
"""

from datetime import datetime, timedelta
from typing import Optional
import html
import json

# Import database and utilities
from src.db.postgres_backend import PostgresBackend
from src.logging_utils import get_logger

logger = get_logger(__name__)


async def get_eisv_history_fragment(
    db: PostgresBackend,
    agent_id: str,
    range_str: str = "24h"
) -> str:
    """
    Get EISV history data as JSON for Chart.js.

    Args:
        db: Database backend
        agent_id: Agent UUID
        range_str: Time range (1h, 24h, 7d, 30d)

    Returns:
        JSON string with chart data
    """
    # Parse range
    range_hours = {
        "1h": 1,
        "24h": 24,
        "7d": 24 * 7,
        "30d": 24 * 30
    }.get(range_str, 24)

    start_time = datetime.utcnow() - timedelta(hours=range_hours)

    try:
        # Query audit events for this agent
        # Note: query_audit_events uses start_time, not since
        events = await db.query_audit_events(
            agent_id=agent_id,
            event_type="checkin",
            start_time=start_time,
            limit=500
        )

        # Transform to chart data
        # AuditEvent has: ts, event_id, event_type, agent_id, session_id, confidence, payload, raw_hash
        labels = []
        energy = []
        integrity = []
        entropy = []
        void_values = []
        coherence = []

        for event in events:
            # AuditEvent.payload contains the data dict
            payload = event.payload if event.payload else {}
            eisv = payload.get("eisv", {})

            # Format timestamp for chart labels
            labels.append(event.ts.isoformat() if event.ts else "")
            energy.append(eisv.get("E", 0))
            integrity.append(eisv.get("I", 0))
            entropy.append(eisv.get("S", 0))
            void_values.append(eisv.get("V", 0))

            # Calculate coherence: (E + I) / 2 - (S + V) / 4
            e, i, s, v = eisv.get("E", 0), eisv.get("I", 0), eisv.get("S", 0), eisv.get("V", 0)
            coh = (e + i) / 2 - (s + v) / 4
            coherence.append(max(0, min(1, coh)))

        return json.dumps({
            "labels": labels,
            "datasets": {
                "energy": energy,
                "integrity": integrity,
                "entropy": entropy,
                "void": void_values,
                "coherence": coherence
            }
        })

    except Exception as e:
        logger.error(f"Failed to get EISV history: {e}")
        return '{"error": "Failed to load history"}'


async def get_agent_incidents_fragment(
    db: PostgresBackend,
    agent_id: str,
    limit: int = 20
) -> str:
    """
    Get recent incidents for an agent as HTML.

    Args:
        db: Database backend
        agent_id: Agent UUID
        limit: Max incidents to return

    Returns:
        HTML fragment with incident list
    """
    try:
        # Query significant events (all types, then filter)
        events = await db.query_audit_events(
            agent_id=agent_id,
            event_type=None,  # All types
            limit=limit
        )

        # Filter to significant events
        significant_types = {"governance_decision", "risk_threshold", "pause", "resume", "calibration"}
        significant = []
        for event in events:
            if event.event_type in significant_types:
                significant.append(event)

        if not significant:
            return '<div class="empty-state"><p>No incidents recorded</p></div>'

        html_parts = ['<div class="incident-list">']
        for event in significant[:10]:
            ts = event.ts.isoformat() if event.ts else ""
            event_type = html.escape(event.event_type or "unknown")
            payload = event.payload if event.payload else {}
            summary = html.escape(payload.get("summary", event_type))

            html_parts.append(f'''
                <div class="incident-item incident-{event_type}">
                    <span class="incident-time">{ts}</span>
                    <span class="incident-type">{event_type}</span>
                    <span class="incident-summary">{summary}</span>
                </div>
            ''')
        html_parts.append('</div>')

        return ''.join(html_parts)

    except Exception as e:
        logger.error(f"Failed to get agent incidents: {e}")
        return '<div class="error">Failed to load incidents</div>'
