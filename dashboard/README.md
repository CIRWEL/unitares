# UNITARES Governance Dashboard

**Created:** December 30, 2025
**Last Updated:** February 3, 2026
**Status:** Active

---

## Overview

Web-based dashboard for visualizing multi-agent coordination in real-time. Shows active agents, EISV metrics, knowledge graph discoveries, and system health.

## Access

Once the MCP server is running, access the dashboard at:

- **Local:** http://127.0.0.1:8767/dashboard
- **Root:** http://127.0.0.1:8767/ (also serves dashboard)
- **Via ngrok:** https://unitares.ngrok.io/dashboard

## Features

### Real-Time Metrics
- **Total Agents:** Count of all registered agents
- **Active Agents:** Currently active agents (not paused/archived)
- **Knowledge Discoveries:** Recent entries in the knowledge graph
- **Dialectic Sessions:** Active peer review sessions

### Agent List
- Shows top 20 most recently active agents
- Displays EISV metrics (Energy, Integrity, Coherence)
- Color-coded status indicators (active/paused/archived)
- Real-time updates every 5 seconds

### Recent Discoveries
- Latest knowledge graph entries
- Shows summary, content, agent, and timestamp
- Filtered by discovery type

## Technical Details

### Architecture
- **Frontend:** Pure HTML/CSS/JavaScript (no build step required)
- **Backend:** Uses existing `/v1/tools/call` HTTP API
- **Auto-refresh:** Polls every 5 seconds
- **Responsive:** Works on desktop and mobile

### API Calls
The dashboard makes the following tool calls:
- `list_agents` - Get agent list with metrics
- `search_knowledge_graph` - Get recent discoveries
- `aggregate_metrics` - Get system-wide metrics

### Customization
Edit `dashboard/index.html` to:
- Change refresh interval (default: 5000ms)
- Modify displayed metrics
- Adjust styling/colors
- Add new panels/sections

## Development

### Local Testing
1. Start the MCP server: `python src/mcp_server.py --port 8767`
2. Open browser: http://127.0.0.1:8767/dashboard
3. Edit `dashboard/index.html` and refresh

### Adding New Features
1. Add new API calls in the JavaScript `refresh()` function
2. Update HTML to display new data
3. Style with CSS in the `<style>` section

## Future Enhancements

- [ ] EISV metrics charts over time
- [ ] Agent activity timeline
- [ ] Knowledge graph visualization
- [ ] Filter/search agents
- [ ] Export data (CSV/JSON)
- [ ] Dark/light theme toggle
- [ ] Real-time WebSocket updates (instead of polling)

---

**Status:** MVP Complete - Ready for customer demos

