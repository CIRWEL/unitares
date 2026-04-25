# UNITARES Governance Dashboard

**Created:** December 30, 2025
**Last Updated:** April 2026
**Status:** Active

---

## Overview

Web-based dashboard for visualizing multi-agent coordination in real-time. Shows active agents, EISV metrics, knowledge graph discoveries, and system health.

## Access

Once the MCP server is running, access the dashboard at:

- **Local:** http://127.0.0.1:8767/dashboard
- **Root:** http://127.0.0.1:8767/ (also serves dashboard)
- **Via tunnel:** `https://<your-domain>/dashboard` (if configured)

## Features

### Real-Time Metrics
- **Total Agents:** Count of all registered agents
- **Active Agents:** Currently active agents (not paused/archived)
- **Knowledge Discoveries:** Recent entries in the knowledge graph
- **Dialectic Sessions:** Active peer review sessions

### Agent List
- Loads up to 200 recent agents by default, then renders 20 at a time with "Show more"
- Displays EISV metrics (Energy, Integrity, Coherence)
- Color-coded status indicators (active/paused/archived)
- Real-time updates every 30 seconds
- Local browser state can hide agents via search, status, metrics-only, production-only, trust-tier, and pagination filters

### Recent Discoveries
- Latest knowledge graph entries
- Shows summary, content, agent, and timestamp
- Filtered by discovery type

## Technical Details

### Architecture
- **Frontend:** Pure HTML/CSS/JavaScript (no build step required)
- **Backend:** Uses existing `/v1/tools/call` HTTP API
- **Auto-refresh:** Polls every 30 seconds (with 25s client-side cache)
- **Responsive:** Works on desktop and mobile

### API Calls
The dashboard makes the following tool calls:
- `agent(action='list')` — Get agent list with metrics
- `search_knowledge_graph` — Get recent discoveries
- `get_dialectic_session` / `list_dialectic_sessions` — Dialectic sessions and transcripts

### File Structure
- `index.html` — Main dashboard page
- `styles.css` — Extracted CSS (dark/light theme support)
- `utils.js` — API client, data processing, theme manager
- `components.js` — Reusable UI components

### Customization
Edit the dashboard files to:
- Change refresh interval (default: 30000ms)
- Modify displayed metrics
- Adjust styling/colors
- Add new panels/sections

## Development

### Local Testing
1. Start the MCP server: `python src/mcp_server.py --port 8767`
2. Open browser: http://127.0.0.1:8767/dashboard
3. Edit `dashboard/index.html` and refresh

### Agent Visibility Checks

If an agent has checked in but is not visible in the browser:

1. Clear the agent search box.
2. Set status to `All`.
3. Disable metrics-only and production-only filters.
4. Clear any trust-tier filter by reloading the page.
5. Search by the UUID prefix or exact label.
6. Hard refresh the browser if the API result is correct but the view is stale.

The dashboard API call is the source of truth for the browser list:

```bash
curl -s -X POST http://127.0.0.1:8767/v1/tools/call \
  -H "Authorization: Bearer $UNITARES_HTTP_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"agent","arguments":{"action":"list","include_metrics":true,"recent_days":30,"limit":200,"min_updates":0,"status_filter":"all"}}'
```

If the agent appears in that response, ingestion and persistence are working; the remaining issue is client-side filter, pagination, cache, or stale browser state.

### Adding New Features
1. Add new API calls using `DashboardAPI` in `utils.js`
2. Update HTML in `index.html` to display new data
3. Style with CSS in `styles.css`

## Completed Enhancements

- [x] Filter/search agents
- [x] Export data (CSV/JSON) — via `utils.js` DataProcessor
- [x] Dark/light theme toggle — via ThemeManager
- [x] Dialectic session viewer with filters and transcript display
- [x] Modular component architecture (`components.js`)
- [x] Extracted CSS with theme variables (`styles.css`)
- [x] Loading performance optimization — scoped CSS transitions, reduced API calls, fast DB paths for dialectic

## Future Enhancements

- [ ] EISV metrics charts over time
- [ ] Agent activity timeline
- [ ] Knowledge graph visualization
- [ ] Real-time WebSocket updates (instead of polling)

---

**Status:** Active — Serving at `/dashboard`
