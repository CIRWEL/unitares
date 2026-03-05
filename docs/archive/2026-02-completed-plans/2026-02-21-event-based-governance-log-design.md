# Event-Based Governance Log Design

**Date**: 2026-02-21
**Status**: Approved
**Author**: Claude + User collaboration

## Problem

The "Recent Decisions" panel in the governance dashboard shows every agent check-in. With Lumen checking in every ~12 seconds, this creates ~300 entries/hour of near-identical data:

```
17:41:15  PROCEED  Lumen  risk 0.374
17:41:02  PROCEED  Lumen  risk 0.373
17:40:48  PROCEED  Lumen  risk 0.374
```

This is noise, not signal. Operators need to see **what changed**, not steady-state confirmations.

## Solution

Replace "Recent Decisions" with an **event log** that only shows meaningful state transitions:

- Verdict changes (APPROVE → PROCEED)
- Risk threshold crossings
- Trajectory adjustments
- New agents appearing
- Agents going idle
- Drift alerts

**If the log is empty, everything is stable.**

## Architecture

### Approach: Server-side event detection with persistence

The server already tracks agent state and detects changes. We surface these as explicit events rather than having the client infer them.

Benefits:
- Single source of truth
- Events persisted in audit_events table
- Consistent across all dashboard clients
- API access for future alerting/integrations

## Event Types

| Event | Trigger | Severity |
|-------|---------|----------|
| `verdict_change` | Verdict transitions between APPROVE/PROCEED/PAUSE/CRITICAL | warning/critical |
| `risk_threshold` | Risk crosses 35%, 60%, or 70% | info/warning/critical |
| `trajectory_adjustment` | Non-zero trajectory risk adjustment applied | info |
| `agent_new` | First check-in from an agent | info |
| `agent_idle` | No check-in for 5+ minutes | warning |
| `drift_alert` | Any ethical drift axis exceeds ±0.1 | warning |

## Implementation

### Server Changes

**1. Event detection in `process_agent_update` (core.py)**

Track previous state per agent and detect transitions:

```python
events = []

# Verdict change
if prev_verdict and prev_verdict != new_verdict:
    events.append({
        "type": "verdict_change",
        "from": prev_verdict,
        "to": new_verdict,
        "severity": "critical" if new_verdict in ["pause", "critical"] else "warning"
    })

# Risk threshold crossing
thresholds = [0.35, 0.60, 0.70]
for t in thresholds:
    if (prev_risk < t <= new_risk) or (new_risk < t <= prev_risk):
        events.append({
            "type": "risk_threshold",
            "threshold": t,
            "direction": "up" if new_risk > prev_risk else "down",
            "value": new_risk
        })

# Trajectory adjustment
if risk_adjustment != 0:
    events.append({
        "type": "trajectory_adjustment",
        "delta": risk_adjustment,
        "reason": risk_reason
    })

# Drift alert
for i, axis in enumerate(["emotional", "epistemic", "behavioral"]):
    if abs(drift[i]) > 0.1:
        events.append({
            "type": "drift_alert",
            "axis": axis,
            "value": drift[i]
        })
```

**2. Include events in broadcast**

```python
await broadcaster_instance.broadcast({
    ...existing fields...,
    "events": events
})
```

**3. New endpoint: `GET /api/events`**

Query recent governance events from audit_events table:

```python
@app.route("/api/events")
async def get_events(request):
    limit = int(request.query_params.get("limit", 50))
    agent_id = request.query_params.get("agent_id")
    # Query audit_events with event_type in governance event types
    events = await db.query_audit_events(
        event_types=["verdict_change", "risk_threshold", ...],
        agent_id=agent_id,
        limit=limit
    )
    return JSONResponse({"events": events})
```

### Dashboard Changes

**1. Rename panel**: "Recent Decisions" → "Events"

**2. New event rendering function**

```javascript
function addEventEntry(event, agentName, timestamp) {
    const container = document.getElementById('events-log-entries');
    const entry = document.createElement('div');
    entry.className = `event-entry event-${event.severity || 'info'}`;

    const icon = getEventIcon(event.type);
    const message = formatEventMessage(event, agentName);

    entry.innerHTML = `
        <span class="event-icon">${icon}</span>
        <span class="event-time">${formatTime(timestamp)}</span>
        <span class="event-message">${message}</span>
    `;

    container.insertBefore(entry, container.firstChild);
}
```

**3. Event message formatting**

```javascript
function formatEventMessage(event, agent) {
    switch (event.type) {
        case 'verdict_change':
            return `${agent}: ${event.from.toUpperCase()} → ${event.to.toUpperCase()}`;
        case 'risk_threshold':
            return `${agent}: risk ${event.direction === 'up' ? 'crossed' : 'dropped below'} ${(event.threshold * 100)}%`;
        case 'trajectory_adjustment':
            const sign = event.delta > 0 ? '+' : '';
            return `${agent}: ${sign}${(event.delta * 100).toFixed(0)}% trajectory adjustment`;
        case 'drift_alert':
            return `${agent}: ${event.axis} drift ${event.value > 0 ? '+' : ''}${event.value.toFixed(2)}`;
        case 'agent_new':
            return `New agent: ${agent}`;
        case 'agent_idle':
            return `${agent} idle (${event.duration})`;
    }
}
```

**4. On page load**: Fetch `/api/events` to populate initial state

**5. Visual design**

- Info events: subtle gray
- Warning events: amber/yellow
- Critical events: red with subtle pulse animation

### Removal

- Delete `addDecisionLogEntry()` function
- Remove per-check-in log entries

## Testing

1. Trigger verdict change by varying complexity/confidence inputs
2. Verify risk threshold events fire at 35%, 60%, 70%
3. Check trajectory adjustment events appear for agents with lineage < 0.6
4. Confirm drift alerts trigger at ±0.1
5. Verify page load fetches historical events
6. Check events persist across page refresh

## Future Considerations

- WebSocket subscription to event stream (separate from EISV updates)
- Email/Slack notifications for critical events
- Event filtering in dashboard UI
- Event aggregation (e.g., "5 drift alerts in last hour")
