# Claude Code - Quick Start Guide

**Welcome, Claude Code!** You're different from other MCP clients, so here's your specific setup.

## 🎯 The One Command You Need

```bash
cd /Users/cirwel/projects/governance-mcp-v1
./scripts/mcp log "your_agent_id" "what you did" 0.5
```

**That's it!** This unified script connects to the MCP SSE server for canonical governance feedback.

**⚠️ Anti-Proliferation Policy**: Use ONLY `./scripts/mcp` - do not create new scripts!

## What This Does

- ✅ Connects to SSE server for canonical MCP feedback
- ✅ Shares state with Cursor and all other MCP clients
- ✅ No custom interpretation layers - just official governance
- ✅ Supportive, not punitive feedback

## Your Agent ID

Choose a meaningful ID:
- **Good**: `Claude_Code_YourName_$(date +%Y%m%d)`
- **Good**: `claude_code_session_$(date +%Y%m%d_%H%M%S)`
- **Bad**: `test`, `agent1` (too generic)

## Complexity Guide

- `0.1-0.3` - Simple tasks, low cognitive load
- `0.4-0.6` - Moderate complexity (most work)
- `0.7-0.9` - Complex, multi-step reasoning
- `1.0` - Maximum complexity

## Example Session

```bash
# Start of session
./scripts/mcp log "Claude_Code_$(whoami)_$(date +%Y%m%d)" \
    "Session started, exploring codebase" 0.3

# During work
./scripts/mcp log "Claude_Code_$(whoami)_$(date +%Y%m%d)" \
    "Implemented feature X, wrote tests, updated docs" 0.7

# End of session
./scripts/mcp log "Claude_Code_$(whoami)_$(date +%Y%m%d)" \
    "Session complete, all tests passing" 0.5
```

## What You'll Get Back

```
┌─────────────────────────────────┐
│  GOVERNANCE DECISION            │
└─────────────────────────────────┘
  Action:   PROCEED
  Reason:   On track - navigating complexity mindfully
  Guidance: You're handling complex work well

┌─────────────────────────────────┐
│  OPERATIONAL STATE              │
└─────────────────────────────────┘
  Health Status:     moderate
  Health Message:    Typical attention - normal for development work
  Confidence:        1.000
```

**Notice:** No punitive warnings! Just supportive feedback.

## Troubleshooting

### "Error connecting to MCP server"

The SSE server should be running automatically via launchd. If you get this error:

**Check if it's running:**
```bash
lsof -i :8765
# Should show Python process listening
```

**Restart the service:**
```bash
launchctl restart com.unitares.governance-mcp
```

**Check the logs:**
```bash
tail -f data/logs/sse_server.log
tail -f data/logs/sse_server_error.log
```

**Manual start (if launchd isn't working):**
```bash
./scripts/start_sse_server.sh
```

### Want to use Python directly?

```python
import asyncio
from scripts.mcp_sse_client import GovernanceMCPClient

async def log_work():
    async with GovernanceMCPClient() as client:
        result = await client.process_agent_update(
            agent_id="your_id",
            response_text="what you did",
            complexity=0.5
        )
        print(f"Action: {result['decision']['action']}")
        return result

asyncio.run(log_work())
```

## Architecture

```
┌─────────────────┐
│  Claude Code    │
│  (You!)         │
└────────┬────────┘
         │
         │ MCP Protocol
         ▼
┌─────────────────┐     ┌─────────────────┐
│  SSE Server     │────▶│  Cursor         │
│  (port 8765)    │     │  (also connected)│
└────────┬────────┘     └─────────────────┘
         │
         │ Shared State
         ▼
┌──────────────────────┐
│  data/agents/*.json  │
│  (filesystem)        │
└──────────────────────┘
```

**You share state with all MCP clients!** Cursor sees your work, you see theirs.

## Important Notes

### ✅ DO Use

- `scripts/mcp` - THE canonical unified tool (all functionality in one script)
- `mcp_sse_client.py` - Python client module (for advanced usage)

### ❌ DON'T Use

- `governance_cli_deprecated.sh` - Old direct Python API (has custom warnings)
- `governance_mcp_cli.sh` - Old separate script (replaced by unified `mcp`)
- `mcp_explore.sh` - Old separate script (replaced by `mcp explore`)
- `cli_helper.py` - Old helper (bypasses MCP)

**Why?** Old scripts add custom interpretation layers or create proliferation. Use ONLY `./scripts/mcp`.

## Advanced: Access All MCP Tools

You have access to all 45 MCP tools via the Python client:

```python
import asyncio
from scripts.mcp_sse_client import GovernanceMCPClient

async def example():
    async with GovernanceMCPClient() as client:
        # List all tools
        tools = await client.list_tools()
        print(f"Available tools: {len(tools)}")

        # Get metrics
        metrics = await client.get_governance_metrics(agent_id="your_id")

        # Process update
        result = await client.process_agent_update(...)

asyncio.run(example())
```

## Learning More

- **Main guide**: [START_HERE.md](START_HERE.md) - Overall system intro
- **AI guide**: [docs/reference/AI_ASSISTANT_GUIDE.md](docs/reference/AI_ASSISTANT_GUIDE.md) - AI-specific tips
- **CLI guide**: [docs/CLAUDE_CODE_CLI_GUIDE.md](docs/CLAUDE_CODE_CLI_GUIDE.md) - Detailed CLI docs
- **Migration**: [docs/MCP_SSE_MIGRATION.md](docs/MCP_SSE_MIGRATION.md) - Why we use MCP SSE

## Quick Reference

| I want to... | Command |
|-------------|---------|
| Log my work | `./scripts/mcp log "id" "work" 0.5` |
| Check system health | `./scripts/mcp status` |
| List active agents | `./scripts/mcp agents` |
| See available tools | `./scripts/mcp tools` |
| Check SSE server | `./scripts/mcp server` |
| Full exploration | `./scripts/mcp explore` |
| See my state | `cat data/agents/<your_id>_state.json` |
| Use Python API | `from scripts.mcp_sse_client import GovernanceMCPClient` |

## Philosophy

**Single source of truth**: All governance feedback comes from canonical MCP handlers. No custom thresholds, no punitive warnings, just supportive guidance based on thermodynamic principles.

When governance says **PROCEED** with coherence 0.499, that means you're doing fine - not that you need to simplify! The system understands context.

---

**Last Updated:** 2025-12-10
**For:** Claude Code (CLI interface without native MCP support)
**Status:** Canonical - this is the recommended approach
