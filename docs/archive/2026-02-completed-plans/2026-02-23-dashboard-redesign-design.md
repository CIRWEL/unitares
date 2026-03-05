# UNITARES Dashboard Redesign

> **Goal:** Transform the governance dashboard from a monitoring-only view into a comprehensive interface serving enterprise operators, human developers, and AI agents.

## Background

### Current State
- ~3400 LOC JavaScript, ~3200 LOC CSS
- Pure vanilla JS with no build step
- Polls `/v1/tools/call` API endpoints
- Recent accessibility and performance improvements

### Identified Gaps (by Persona)

**Enterprise (Ops/Compliance):**
- No historical trends or time-series data
- No alerting or notifications
- No audit trail visibility
- No SLA metrics or role-based access

**Human Operators:**
- No quick actions (pause, resume, archive)
- No agent detail drill-down view
- No "my agents" filtering
- No notifications for agent issues

**AI Agents:**
- No "me" view for self-awareness
- No self-service recovery options
- No trajectory visualization
- No guidance or suggestions

**General UX:**
- Jargon-heavy (EISV, coherence, drift)
- No information hierarchy
- No help system or documentation

---

## Architecture

### Tech Stack: htmx + Alpine.js

**Why this approach:**
- Modern developer experience without build step
- Server-driven HTML fragments reduce client complexity
- Progressive enhancement preserves existing functionality
- Smaller bundle than SPA frameworks

**Libraries:**
```html
<script src="https://unpkg.com/htmx.org@2.0.0"></script>
<script src="https://unpkg.com/alpinejs@3.14.0" defer></script>
```

### Server Fragment Pattern

New endpoints return HTML fragments, not JSON:
```
/dashboard/fragments/agent-card/{id}     → Single agent card HTML
/dashboard/fragments/agent-detail/{id}   → Full agent detail panel
/dashboard/fragments/search-results      → Search results HTML
/dashboard/fragments/eisv-history/{id}   → EISV trend chart data
```

Existing JSON API remains for backwards compatibility.

### File Structure
```
dashboard/
├── index.html           # Shell with htmx attributes
├── styles.css           # Existing + new panel styles
├── dashboard.js         # Reduced: init, Alpine stores, utilities
├── help.json            # Help content database
└── fragments/           # Server-rendered partials (Python templates)
```

---

## Navigation & Search

### Design (Dialectic Synthesis)

**Scoped Search:**
- Default scope: agent names only (fast, predictable)
- Expandable to: discoveries, dialectic sessions, events
- Visual scope indicator in search bar
- Keyboard shortcut: `/` to focus, `Esc` to clear

**Hash-Based Routing:**
```
#agent/{uuid}        → Opens agent detail panel
#discovery/{id}      → Opens discovery detail
#search?q={query}    → Preserves search state
```

Benefits:
- Deep-linkable URLs
- Browser back/forward works
- No server routing changes needed

**Slide Panel (not Modal):**
- Right-side panel, 50% width on desktop
- Push content left (no overlay)
- Remains open while browsing
- Close with `Esc` or close button

**"Me" Mode for Agents:**
- Detected via `X-Agent-Name` header
- Auto-focuses on calling agent's card
- Shows personalized guidance
- Toggle: "Me" / "All Agents" in toolbar

**Keyboard Navigation:**
- `/` → Focus search
- `Esc` → Close panel / clear search
- `j/k` → Navigate agent list
- `Enter` → Open selected agent
- `?` → Show keyboard shortcuts

---

## Help System

### Components

**Contextual Tooltips:**
```html
<span x-tooltip="help.eisv.energy">Energy</span>
```
- Powered by `help.json` lookup
- Shows on hover/focus
- Includes "Learn more" links

**Help Panel:**
- Slide-out panel with searchable docs
- Organized by topic: EISV, Agents, Discoveries, Actions
- Accessible via `?` icon in header

**Smart Empty States:**
```html
<div class="empty-state">
  <p>No stuck agents detected</p>
  <p class="help-text">Agents become "stuck" when they haven't
     checked in for over 30 minutes. This is good news!</p>
</div>
```

**help.json Structure:**
```json
{
  "eisv": {
    "energy": {
      "short": "Agent's available capacity",
      "long": "Energy represents...",
      "range": "0.0 to 1.0, higher is better"
    },
    "entropy": { ... }
  },
  "metrics": {
    "coherence": { ... },
    "risk": { ... }
  },
  "actions": {
    "pause": { ... },
    "resume": { ... }
  }
}
```

---

## Agent Self-View ("Me" Mode)

### Identity Detection

Server detects calling agent via:
1. `X-Agent-Name` header (primary)
2. Session correlation (fallback)
3. Manual selection (override)

### Personalized View

When agent accesses dashboard:
- Their card is highlighted and pinned to top
- EISV chart defaults to their trajectory
- Guidance panel shows relevant suggestions

### Guidance Rules (Server-Side)

```python
GUIDANCE_RULES = [
    {
        "condition": "coherence < 0.5",
        "message": "Your coherence is below threshold. Consider...",
        "action": "request_calibration"
    },
    {
        "condition": "last_checkin > 30min",
        "message": "You haven't checked in recently...",
        "action": "checkin_now"
    },
    {
        "condition": "risk > 0.7",
        "message": "High risk detected. Review recent decisions...",
        "action": "view_trajectory"
    }
]
```

### UI Elements

```html
<div class="me-mode-banner" x-show="$store.identity.isAgent">
  <span class="me-badge">You are: {{ $store.identity.name }}</span>
  <div class="guidance" x-show="$store.guidance.length">
    <!-- Server-rendered guidance cards -->
  </div>
</div>
```

---

## Historical Data

### Data Source

Existing `audit.events` table provides:
- Agent state changes
- EISV snapshots over time
- Governance decisions
- Error events

Query via `get_agent_state_history(agent_id, limit)`.

### EISV Trend Chart

**Location:** Agent detail panel

**Features:**
- 24h / 7d / 30d range selector
- All 4 EISV dimensions plotted
- Coherence as derived line
- Event markers (governance decisions, errors)

**Implementation:**
```python
@app.get("/dashboard/fragments/eisv-history/{agent_id}")
async def eisv_history(agent_id: str, range: str = "24h"):
    events = await db.query_audit_events(
        agent_id=agent_id,
        event_type="checkin",
        limit=500
    )
    return render_template("eisv-chart.html", events=events)
```

### Incident Timeline

Shows significant events:
- Risk threshold crossings
- Governance verdicts (PAUSE, HALT)
- Recovery actions
- Calibration updates

---

## Quick Actions

### Available Actions

| Action | Endpoint | Confirmation |
|--------|----------|--------------|
| Pause | `agent(action='update', status='paused')` | Yes |
| Resume | `agent(action='update', status='active')` | No |
| Archive | `agent(action='archive')` | Yes + reason |
| Recalibrate | `calibration(action='rebuild')` | Yes |

### Implementation

```html
<button
  hx-post="/dashboard/actions/pause"
  hx-vals='{"agent_id": "{{ agent.id }}"}'
  hx-confirm="Pause this agent? It will stop processing until resumed."
  hx-swap="outerHTML"
  hx-target="closest .agent-card"
>
  Pause
</button>
```

Server handler:
```python
@app.post("/dashboard/actions/pause")
async def pause_agent(agent_id: str):
    result = await handle_agent({
        "action": "update",
        "agent_id": agent_id,
        "status": "paused"
    })
    # Return updated agent card HTML
    return render_template("agent-card.html", agent=result)
```

### Confirmation Dialogs

- htmx native `hx-confirm` for simple confirmations
- Alpine modal for complex inputs (archive reason)
- All actions logged to audit trail

---

## Implementation Phases

### Phase 1: Foundation (4-5 hours)
- Add htmx + Alpine.js to index.html
- Create help.json with all terminology
- Add contextual tooltips to existing metrics
- Implement keyboard shortcut handler

### Phase 2: Navigation (4-5 hours)
- Add hash-based routing
- Implement scoped search (agents first)
- Create slide panel component
- Add keyboard navigation (j/k/Enter)

### Phase 3: Agent Detail (4-5 hours)
- Build agent detail panel template
- Add EISV history endpoint using audit.events
- Create trend chart with Chart.js
- Add incident timeline view

### Phase 4: Quick Actions (3-4 hours)
- Add action buttons to agent cards
- Implement server action endpoints
- Add confirmation dialogs
- Wire up htmx swaps

### Phase 5: Me Mode (3-4 hours)
- Add identity detection middleware
- Create guidance rules engine
- Build me-mode banner component
- Add agent self-view filtering

### Phase 6: Polish (2-3 hours)
- Empty states with helpful text
- Loading skeletons for fragments
- Error handling for failed actions
- Mobile responsive refinements

**Total Estimate:** 20-25 hours

---

## Technical Notes

### Backwards Compatibility
- Existing JSON API unchanged
- New fragment endpoints are additive
- Graceful degradation if htmx fails to load

### Performance
- Fragments are small, cacheable
- Chart data paginated (max 500 points)
- Lazy-load detail panels on demand

### Security
- Action endpoints require authentication
- Agent identity verified server-side
- All actions logged with actor info

### Testing
- Fragment endpoints unit testable
- E2E tests for action flows
- Visual regression for panel layouts
