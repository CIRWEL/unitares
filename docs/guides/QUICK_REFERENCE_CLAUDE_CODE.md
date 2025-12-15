# Quick Reference - Claude Code

## The One Command
```bash
./scripts/mcp log "your_id" "what you did" 0.5
```

**⚠️ Use ONLY this unified script - do not create new scripts!**

## What You Get
- ✅ Canonical MCP handler feedback
- ✅ Shared state with all MCP clients
- ✅ Supportive, context-aware guidance
- ❌ No punitive custom warnings

## Complexity Scale
- `0.1-0.3` Simple tasks
- `0.4-0.6` Moderate work (most common)
- `0.7-0.9` Complex reasoning
- `1.0` Maximum complexity

## Troubleshooting

**SSE server runs automatically via launchd**

```bash
# Check if running
lsof -i :8765

# Restart service
launchctl restart com.unitares.governance-mcp

# Check logs
tail -f data/logs/sse_server.log
```

## Full Guides
- [CLAUDE_CODE_START_HERE.md](CLAUDE_CODE_START_HERE.md) - Full guide
- [.agent-guides/FUTURE_CLAUDE_CODE_AGENTS.md](.agent-guides/FUTURE_CLAUDE_CODE_AGENTS.md) - Context

## Don't Use
- ❌ `governance_cli_deprecated.sh`
- ❌ `governance_mcp_cli.sh` (replaced by unified `mcp`)
- ❌ `mcp_explore.sh` (use `./scripts/mcp explore`)
- ❌ `cli_helper.py`
- ❌ Creating new scripts (use existing `./scripts/mcp`)

---
**Updated:** 2025-12-10
