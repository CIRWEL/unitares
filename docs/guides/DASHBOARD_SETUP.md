# Dashboard Setup Guide

**Created:** December 30, 2025  
**Last Updated:** January 15, 2026  
**Status:** Active

---

## Quick Start

The web dashboard is automatically available when the MCP server is running.

### Access the Dashboard

1. **Start the server:**

   ```bash
   python src/mcp_server_sse.py --port 8765
   ```

2. **Open in browser:**

   - Local: [http://127.0.0.1:8765/dashboard](http://127.0.0.1:8765/dashboard)
   - Root: [http://127.0.0.1:8765/](http://127.0.0.1:8765/)
   - Via ngrok: [https://unitares.ngrok.io/dashboard](https://unitares.ngrok.io/dashboard)

### What You'll See

- **Stats Cards:** Total agents, active agents, discoveries, dialectic sessions
- **Agent List:** Top 20 most recently active agents with EISV metrics
- **Recent Discoveries:** Latest knowledge graph entries
- **Auto-refresh:** Updates every 10 seconds

## Features

### Real-Time Metrics

- Total agent count
- Active vs paused/archived breakdown
- Knowledge graph discovery count
- Dialectic session activity

### Agent Monitoring

- Agent ID and display name
- EISV metrics (Energy, Integrity, Coherence)
- Status indicators (active/paused/archived)
- Last update timestamp

### Knowledge Graph

- Recent discoveries with summaries
- Discovery type and agent attribution
- Timestamps

## Customization

Edit `dashboard/index.html` to:

- Change refresh interval (search for `setInterval`)
- Modify displayed metrics
- Adjust colors/styling
- Add new panels

## Troubleshooting

### Dashboard Not Loading

1. **Check server is running:**

   ```bash
   curl http://127.0.0.1:8765/health
   ```

2. **Check dashboard file exists:**

   ```bash
   ls dashboard/index.html
   ```

3. **Check browser console** for JavaScript errors

### API Errors

The dashboard uses `/v1/tools/call` endpoint. If you see API errors:

- Verify server is running
- Check authentication (if HTTP_API_TOKEN is set)
- Check browser network tab for failed requests

### No Data Showing

- Ensure agents exist: `list_agents` tool should return agents
- Check knowledge graph has entries: `search_knowledge_graph` should return discoveries
- Verify server logs for errors

## For Customer Demos

### Best Practices

1. **Have agents active** - Start a few agents doing work before demo
2. **Show knowledge graph** - Make some discoveries so the graph has content
3. **Explain EISV metrics** - What Energy, Integrity, Coherence mean
4. **Show real-time updates** - Let it refresh to show live coordination

### Demo Script

1. Open dashboard
2. Point out total agents (shows scale)
3. Show active agents with metrics (shows coordination)
4. Highlight recent discoveries (shows knowledge sharing)
5. Explain how agents coordinate via shared knowledge graph

## Future Enhancements

- [ ] EISV charts over time
- [ ] Agent activity timeline
- [ ] Knowledge graph visualization
- [ ] Filter/search agents
- [ ] Export data
- [ ] WebSocket real-time updates

---

**Status:** MVP Complete - Ready for demos
