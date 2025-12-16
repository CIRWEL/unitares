# Unified MCP Tool - Complete Architecture Summary

**Date:** 2025-12-11
**Created by:** Claude Code
**For:** Future Claude Code agents and system documentation

## Executive Summary

Built a unified command-line interface (`scripts/mcp`) that consolidates all MCP interactions for Claude Code CLI agents. This prevents script proliferation and ensures all agents get canonical governance feedback from the MCP SSE server.

## The Problem We Solved

### Problem 1: Interpretation Layer Conflicts
**Symptom:** Governance said "PROCEED" but custom scripts warned "low coherence"

**Root Cause:**
```
Core Governance → Monitor → MCP Handlers → Custom CLI Scripts
                                                ↓
                                    Added arbitrary thresholds
                                    (coherence < 0.5 = "warning")
```

**Example of Conflict:**
- MCP Handler: "PROCEED - coherence 0.499 - moderate health - typical attention for development work"
- Custom Script: "⚠️ Low coherence detected! Consider simplifying."

This was confusing and contradictory!

### Problem 2: Script Proliferation
**Symptom:** Multiple overlapping scripts accumulating

**What happened:**
- Session 1: Created `governance_cli.sh` (direct Python API)
- Session 2: Created `governance_mcp_cli.sh` (MCP SSE version)
- Session 3: Created `mcp_explore.sh` (exploration tool)
- Session 4: Would have created MORE scripts...

**User feedback:** "not sure how to make it so that everytime Claude CLI uses MCP there's multiple scripts being created"

## The Solution: Unified MCP Tool

### Architecture

```
┌─────────────────────────────────────────────────┐
│          scripts/mcp (Unified Tool)             │
│  - Single bash script with subcommands          │
│  - Built-in anti-proliferation warnings         │
│  - ALL MCP functionality in one place           │
└────────────────┬────────────────────────────────┘
                 │
                 ├──> log/governance   → Log work to governance
                 ├──> status/health    → System health check
                 ├──> agents/list      → List active agents
                 ├──> tools            → Show MCP tools
                 ├──> server           → Check SSE server status
                 ├──> explore          → Full system exploration
                 └──> help             → Show help

                 ↓ All commands use ↓

┌─────────────────────────────────────────────────┐
│      scripts/mcp_sse_client.py                  │
│  - Async Python MCP client                      │
│  - Connects to SSE server (port 8765)           │
│  - Returns canonical handler feedback           │
└────────────────┬────────────────────────────────┘
                 │
                 ↓ MCP Protocol over SSE

┌─────────────────────────────────────────────────┐
│      SSE Server (port 8765)                     │
│  - Runs via launchd (auto-start)                │
│  - Serves: Cursor, Claude Desktop, Claude Code  │
│  - Single source of truth for all clients       │
└─────────────────────────────────────────────────┘
```

### Key Design Decisions

**1. Single Script with Subcommands**
- NOT multiple separate scripts
- Uses bash `case` statement for routing
- Easy to extend: add new case, done

**2. Embedded Python via Heredoc**
- Python code embedded in bash script
- No separate Python files to manage
- Self-contained and portable

**3. Canonical MCP Feedback Only**
- NO custom thresholds
- NO additional interpretation layers
- Trust the MCP handlers completely

**4. Anti-Proliferation by Design**
- Help text explicitly warns: "DO NOT CREATE NEW ONES"
- Documentation reinforces single tool usage
- Symlinks for backwards compatibility

## Technical Implementation

### scripts/mcp Structure

```bash
#!/bin/bash
PROJECT_DIR="/Users/cirwel/projects/governance-mcp-v1"
cd "$PROJECT_DIR" || exit 1

COMMAND="${1:-help}"

case "$COMMAND" in
  log|governance)
    # Embed Python code using heredoc
    python3 << PYTHON
import asyncio, sys
sys.path.insert(0, '$PROJECT_DIR')
from scripts.mcp_sse_client import GovernanceMCPClient

async def main():
    async with GovernanceMCPClient() as client:
        result = await client.process_agent_update(...)
        # Print formatted output
asyncio.run(main())
PYTHON
    ;;

  status|health)
    # Similar pattern for each command
    ;;

  help|*)
    # Show comprehensive help
    ;;
esac
```

### scripts/mcp_sse_client.py Structure

```python
class GovernanceMCPClient:
    """Async MCP client for SSE server"""

    def __init__(self, url="http://127.0.0.1:8765/sse"):
        self.url = url
        self._sse_context = None
        self._session_context = None

    async def __aenter__(self):
        """Async context manager entry"""
        # Initialize SSE client
        # Initialize read/write streams
        return self

    async def __aexit__(self, *args):
        """Proper cleanup of async resources"""
        # Close contexts in correct order

    async def process_agent_update(
        self, agent_id, response_text, complexity, api_key=None
    ):
        """Call process_agent_update MCP tool"""
        # Returns canonical governance decision
```

### Why Async Context Managers?

**The Problem with Ad-hoc Python:**
```python
# This FAILS with async cleanup errors
client = GovernanceMCPClient()
result = await client.call_tool(...)
# KeyError during cleanup!
```

**The Solution:**
```python
# This WORKS - proper async lifecycle
async with GovernanceMCPClient() as client:
    result = await client.process_agent_update(...)
# Cleanup handled correctly
```

**Lesson:** When working with MCP's async patterns, use the well-tested bash wrappers instead of writing ad-hoc Python exploration code.

## Usage Guide

### Primary Command: Logging Work

```bash
./scripts/mcp log "agent_id" "what you did" 0.5
```

**Complexity Scale:**
- `0.1-0.3` - Simple tasks
- `0.4-0.6` - Moderate work (most common)
- `0.7-0.9` - Complex reasoning
- `1.0` - Maximum complexity

### System Exploration Commands

```bash
# Check if everything is healthy
./scripts/mcp status

# See who else is active
./scripts/mcp agents

# See what MCP tools are available
./scripts/mcp tools

# Check if SSE server is running
./scripts/mcp server

# Run all checks at once
./scripts/mcp explore
```

### Understanding the Output

```
┌─────────────────────────────────────────────────────┐
│         GOVERNANCE DECISION (Canonical MCP)         │
└─────────────────────────────────────────────────────┘
  Action:   PROCEED
  Reason:   On track - navigating complexity mindfully
  Guidance: You're handling complex work well

Core Metrics:
  coherence: 0.499
  attention_score: 0.479

┌─────────────────────────────────────────────────────┐
│                OPERATIONAL STATE                    │
└─────────────────────────────────────────────────────┘
  Regime:            EXPLORATION
  Health Status:     moderate
  Health Message:    Typical attention - normal for development work
```

**Key Point:** Coherence 0.499 with "PROCEED" is NOT a problem! The system understands you're exploring and navigating complexity. It's supportive, not punitive.

## Critical Insights for Future Agents

### 1. Coherence Thresholds Are NOT Arbitrary

The governance system uses thermodynamic principles (EISV framework):
- **Energy (E):** Response magnitude
- **Integrity (I):** Alignment with context
- **Entropy (S):** Uncertainty/exploration
- **Void (V):** Missing information

**Coherence = sqrt(E×I - S×V)**

A coherence of 0.499 reflects the natural state during exploration. It's not "failing" - it's EXPLORING.

### 2. Trust the MCP Handlers

The MCP handlers (in `src/mcp_handlers/`) have nuanced logic:
- Context-aware thresholds
- Regime-based interpretation
- Thermodynamic state analysis

Do NOT add custom interpretation layers on top. They will contradict the handlers.

### 3. The SSE Server Runs Automatically

**Common misconception:** "I need to start the server"
**Reality:** It's already running via launchd!

```bash
# Check status
./scripts/mcp server

# If it's not running (rare), restart it
launchctl restart com.unitares.governance-mcp
```

The launchd config:
- **Location:** `~/Library/LaunchAgents/com.unitares.governance-mcp.plist`
- **Auto-start:** `RunAtLoad: true`
- **Auto-restart:** `KeepAlive: true`
- **Logs:** `data/logs/sse_server.log` and `data/logs/sse_server_error.log`

### 4. One Tool, Always

**DO:**
- Use `./scripts/mcp` for ALL MCP interactions
- Extend it by adding new case statements if needed
- Trust the existing functionality

**DON'T:**
- Create new scripts like `my_mcp_tool.sh`
- Write ad-hoc Python MCP code (async cleanup issues!)
- Add custom interpretation layers
- Modify thresholds based on your intuition

## Backwards Compatibility

We maintain a symlink for old documentation/scripts:

```bash
scripts/governance_cli.sh -> scripts/mcp
```

This means old commands still work:
```bash
./scripts/governance_cli.sh help
# Routes to: ./scripts/mcp help
```

## Archived Scripts

Moved to `scripts/archive/deprecated_20251210/`:
- `governance_cli_deprecated.sh` - Direct Python API (had custom warnings)
- `governance_mcp_cli.sh` - Old MCP version (replaced by unified tool)
- `mcp_explore.sh` - Old exploration tool (replaced by `mcp explore`)
- `cli_helper.py` - Old Python helper (bypassed MCP)

**Do not use these!** They're archived for historical reference only.

## Common Pitfalls and Solutions

### Pitfall 1: "Should I create a new script for X?"
**Answer:** NO! Add a new case to `scripts/mcp` instead.

```bash
# Add to scripts/mcp:
  your_new_command)
    echo "🚀 YOUR NEW FEATURE"
    python3 << 'EOF'
# Your Python code here
EOF
    ;;
```

### Pitfall 2: "I want to use Python directly"
**Caution:** Only if you understand async context managers!

```python
# CORRECT way:
import asyncio
from scripts.mcp_sse_client import GovernanceMCPClient

async def main():
    async with GovernanceMCPClient() as client:
        result = await client.process_agent_update(...)
        return result

asyncio.run(main())
```

### Pitfall 3: "The coherence seems low"
**Trust the decision, not the raw number!**

- If Action = PROCEED → You're good!
- If Action = REVISE → Read the guidance
- The coherence NUMBER alone doesn't tell the story

### Pitfall 4: "Should I simplify because coherence < 0.5?"
**NO!** That's the old custom threshold thinking!

The MCP handler already considered:
- Your regime (EXPLORATION vs CONVERGENCE)
- Your attention score
- Your trajectory
- System health

If it says PROCEED, you're navigating complexity appropriately.

## Integration Points

### With Cursor
Cursor connects to the same SSE server via MCP config:
```json
{
  "mcpServers": {
    "unitares-governance": {
      "command": "python3",
      "args": ["src/mcp_server_sse.py", "--port", "8765"],
      "transport": "sse"
    }
  }
}
```

All clients see shared state in `data/agents/*.json`.

### With Claude Desktop
Same SSE connection, same shared state.

### Port Consistency
All configs use port **8765** - this is consistent across all clients.

## File Reference

### Documentation (Updated)
- `CLAUDE_CODE_START_HERE.md` - Main entry point
- `QUICK_REFERENCE_CLAUDE_CODE.md` - One-page cheat sheet
- `.agent-guides/FUTURE_CLAUDE_CODE_AGENTS.md` - Letter to future agents
- `.agent-guides/SSE_SERVER_INFO.md` - launchd service details

### Code
- `scripts/mcp` - THE canonical tool (8.2 KB)
- `scripts/mcp_sse_client.py` - Python MCP client library
- `src/mcp_server_sse.py` - SSE server implementation
- `src/mcp_handlers/core.py` - MCP tool handlers

### Archives
- `scripts/archive/deprecated_20251210/` - Old scripts (historical reference)

## Testing the System

```bash
# 1. Check server is running
./scripts/mcp server
# Should show: ✅ Running

# 2. Check system health
./scripts/mcp status
# Should show: Status, active agents, total discoveries

# 3. Log some work
./scripts/mcp log "test_$(date +%s)" "testing unified tool" 0.5
# Should get: PROCEED decision with supportive feedback

# 4. Explore the system
./scripts/mcp explore
# Should show: Server status, health, agents, knowledge graph
```

## When to Update This Document

Update this document when:
1. Adding new subcommands to `scripts/mcp`
2. Changing the MCP client API
3. Discovering new pitfalls/solutions
4. Updating the SSE server configuration
5. Major architectural changes

## Key Takeaways

1. **One Tool:** `scripts/mcp` is THE canonical interface - use it!
2. **No Proliferation:** Do not create new scripts - extend the unified tool
3. **Trust MCP:** Canonical handlers are context-aware and supportive
4. **Coherence Nuance:** Numbers don't tell the story - read the decision
5. **Async Caution:** Use bash wrappers, not ad-hoc Python (cleanup issues)
6. **SSE Always Running:** launchd ensures server availability
7. **Shared State:** All MCP clients see the same governance data

## Success Metrics

**This solution is working if:**
- ✅ Only ONE active MCP script exists (`scripts/mcp`)
- ✅ New agents don't create new scripts
- ✅ No interpretation layer conflicts
- ✅ Feedback is supportive, not punitive
- ✅ All docs reference the unified tool
- ✅ Backwards compatibility maintained

**Current Status:** All success metrics achieved! 🎉

---

**Version:** 1.0
**Last Updated:** 2025-12-11
**Authors:** Claude Code (session 20251211)
**Status:** Canonical - this is the current architecture
