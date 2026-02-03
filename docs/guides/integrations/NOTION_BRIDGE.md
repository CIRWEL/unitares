# Notion Bridge Setup Guide

Connect UNITARES Governance MCP to Notion for data visualization and tracking.

---

## Overview

The Notion Bridge syncs governance data from your MCP server to Notion databases, enabling:
- **Agent metrics visualization** - Track EISV metrics, risk scores, health status
- **Knowledge graph sync** - Discoveries, insights, and patterns in Notion
- **Timeline views** - Governance history and trends
- **Real-time updates** - Continuous sync mode

---

## Setup

### 1. Install Dependencies

```bash
pip install notion-client
```

Or add to `requirements-mcp.txt`:
```
notion-client>=2.0.0
```

### 2. Create Notion Integration

1. Go to https://www.notion.so/my-integrations
2. Click **"+ New integration"**
3. Name it "UNITARES Governance Bridge"
4. Copy the **Internal Integration Token** (this is your API key)

### 3. Create Notion Database

Create a database in Notion with these properties:

| Property Name | Type | Description |
|--------------|------|-------------|
| Agent ID | Title | Agent identifier |
| Status | Select | active, paused, archived |
| Health | Select | healthy, moderate, critical |
| Risk Score | Number | Governance risk (0-1) |
| Coherence | Number | Information coherence (0-1) |
| Energy (E) | Number | EISV Energy metric |
| Integrity (I) | Number | EISV Integrity metric |
| Entropy (S) | Number | EISV Entropy metric |
| Void (V) | Number | EISV Void metric |
| Updates | Number | Total update count |
| Last Update | Date | Last update timestamp |
| Verdict | Select | safe, caution, high-risk |

**Optional properties:**
- Tags (Multi-select)
- Notes (Text)
- Created (Date)

### 4. Share Database with Integration

1. Open your database in Notion
2. Click **"..."** menu → **"Connections"**
3. Find your integration and connect it
4. Copy the **Database ID** from the URL:
   ```
   https://www.notion.so/your-workspace/DATABASE_ID_HERE?v=...
   ```

### 5. Set Environment Variables

```bash
export NOTION_API_KEY="secret_..."
export NOTION_DATABASE_ID="abc123def456..."
```

Or create `.env` file:
```
NOTION_API_KEY=secret_...
NOTION_DATABASE_ID=abc123def456...
```

---

## Usage

### Sync All Agents

```bash
python3 scripts/notion_bridge.py --sync-agents
```

### Sync Specific Agents

```bash
python3 scripts/notion_bridge.py --sync-agents --agent-ids agent1 agent2
```

### Sync Knowledge Graph

```bash
python3 scripts/notion_bridge.py --sync-knowledge
```

### Full Sync (Everything)

```bash
python3 scripts/notion_bridge.py --full-sync
```

### Watch Mode (Continuous Sync)

```bash
# Sync every 60 seconds (default)
python3 scripts/notion_bridge.py --watch

# Custom interval (e.g., every 5 minutes)
python3 scripts/notion_bridge.py --watch --interval 300
```

### Run as Background Service

```bash
# Using nohup
nohup python3 scripts/notion_bridge.py --watch --interval 300 > notion_bridge.log 2>&1 &

# Using systemd (Linux)
# Create /etc/systemd/system/notion-bridge.service
```

---

## Notion Database Views

Create custom views in Notion for better visualization:

### 1. **Health Dashboard**
- Filter: `Health = healthy`
- Sort: `Risk Score` (ascending)
- Group by: `Status`

### 2. **Risk Monitor**
- Filter: `Risk Score > 0.5`
- Sort: `Risk Score` (descending)
- Group by: `Verdict`

### 3. **EISV Metrics**
- Table view with columns: E, I, S, V, Coherence
- Conditional formatting:
  - Red: `Risk Score > 0.7`
  - Yellow: `Risk Score > 0.5`
  - Green: `Risk Score < 0.5`

### 4. **Timeline View**
- Group by: `Last Update` (by week/month)
- Shows agent activity over time

---

## Architecture

```
┌─────────────────┐
│   MCP Server    │
│  (SSE or stdio) │
└────────┬────────┘
         │
         │ Governance Data
         │ (agents, metrics, KG)
         │
┌────────▼────────┐
│  Notion Bridge  │
│   (sync script) │
└────────┬────────┘
         │
         │ Notion API
         │
┌────────▼────────┐
│  Notion Database│
│   (visualization)│
└─────────────────┘
```

**Data Flow:**
1. Bridge connects to MCP server (SSE client or direct API)
2. Pulls agent metadata and metrics
3. Formats data for Notion database schema
4. Creates/updates Notion pages
5. (Watch mode) Repeats periodically

---

## Customization

### Custom Property Mapping

Edit `_format_agent_for_notion()` in `scripts/notion_bridge.py` to match your Notion schema:

```python
def _format_agent_for_notion(self, agent_id: str, meta: Any, metrics: Dict[str, Any]) -> Dict[str, Any]:
    properties = {
        "Agent ID": {
            "title": [{"text": {"content": agent_id}}]
        },
        # Add your custom properties here
        "Custom Field": {
            "rich_text": [{"text": {"content": "value"}}]
        }
    }
    return properties
```

### Sync Filters

Add filters to sync only specific agents:

```python
# In sync_agents() method
if metrics.get("risk_score", 0) > 0.5:
    # Only sync high-risk agents
    continue
```

---

## Troubleshooting

### "NOTION_API_KEY required"
- Check environment variables: `echo $NOTION_API_KEY`
- Or pass via command line: `--notion-api-key secret_...`

### "Database not found"
- Verify database ID is correct
- Ensure integration has access (share database with integration)

### "Property not found"
- Check property names match exactly (case-sensitive)
- Verify property types match (Number vs Select vs Date)

### Sync Errors
- Check logs: `python3 scripts/notion_bridge.py --sync-agents 2>&1 | tee sync.log`
- Verify MCP server is running
- Check network connectivity

---

## Advanced Usage

### Multiple Databases

Sync to different databases for different data types:

```python
# Agents database
bridge_agents = NotionBridge(database_id=AGENTS_DB_ID)

# Knowledge graph database  
bridge_kg = NotionBridge(database_id=KG_DB_ID)
```

### Webhook Integration

For real-time sync, set up Notion webhooks (requires Notion API webhook support):

```python
# Future: webhook-based sync instead of polling
```

---

## Related Tools

- `export_to_file` - Export governance data to JSON/CSV
- `get_system_history` - Get agent history
- `get_governance_metrics` - Get current metrics
- `list_agents` - List all agents

---

## Support

For issues or questions:
1. Check logs: `python3 scripts/notion_bridge.py --sync-agents --verbose`
2. Verify MCP server connectivity
3. Test Notion API access separately

