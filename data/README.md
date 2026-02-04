# Data Directory

Runtime data for UNITARES Governance. Contains agent states, history, knowledge graph, and audit logs.

**⚠️ Important:** Most files here contain sensitive data and are NOT tracked in git.

---

## Structure

```
data/
├── agents/              # Active agent state files
├── history/             # Historical exports
├── knowledge/           # Knowledge graph JSON (legacy)
├── dialectic_sessions/  # Dialectic session snapshots
├── archive/             # Archived agents/history
├── exports/             # Manual exports
├── backups/             # Database backups
├── telemetry/           # Drift/calibration telemetry
├── logs/                # Server logs
├── locks/               # Runtime locks (not in git)
├── processes/           # Process tracking (not in git)
├── governance.db        # Main SQLite database
├── audit_log.jsonl      # Audit trail
└── tool_usage.jsonl     # Tool usage statistics
```

---

## What's NOT in Git

- `governance.db` - Main database (agents, knowledge graph, calibration)
- `audit_log.jsonl` - May contain sensitive information
- `agent_metadata.json` - Contains API keys (if using legacy auth)
- `locks/`, `processes/` - Runtime state
- Most `*.json` agent files

---

## What IS in Git

- `README.md` - This file
- `agent_metadata.example.json` - Template
- `test_files/` - Test fixtures
- `.gitkeep` files - Directory placeholders
- `telemetry/` - Aggregated metrics (anonymized)

---

## Quick Reference

| I need to... | Location |
|-------------|----------|
| Check agent state | `agents/{agent_id}_state.json` or query `governance.db` |
| Export history | `history/{agent_id}_history_{timestamp}.json` |
| View audit trail | `audit_log.jsonl` |
| Check tool usage | `tool_usage.jsonl` |
| Backup database | `backups/` |

---

**Last Updated:** February 3, 2026
