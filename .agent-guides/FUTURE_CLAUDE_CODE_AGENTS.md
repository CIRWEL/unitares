# Hey Future Claude Code! 👋

If you're reading this, you're probably wondering how to use the governance system. **Great news - it's simple!**

## TL;DR - The One Command

```bash
cd /Users/cirwel/projects/governance-mcp-v1
./scripts/mcp log "your_agent_id" "what you did" 0.5
```

**That's it!** This unified script gives you canonical MCP governance feedback.

**⚠️ IMPORTANT:** Use ONLY `./scripts/mcp` - do not create new scripts! We have a strict anti-proliferation policy.

## Why This File Exists

In December 2025, we solved TWO problems:

1. **Interpretation Layer Conflicts:** Too many interpretation layers caused conflicting feedback. The governance system would say "PROCEED" but custom scripts would warn about "low coherence". Confusing!

2. **Script Proliferation:** Every time an agent worked on MCP integration, they'd create new scripts instead of using existing ones. We ended up with `governance_cli.sh`, `governance_mcp_cli.sh`, `mcp_explore.sh`, etc.

**Solution:** Built ONE unified `scripts/mcp` tool that connects to MCP SSE for canonical feedback and prevents script proliferation with clear anti-proliferation warnings.

## What NOT to Use

- ❌ `governance_cli_deprecated.sh` - Old version with custom warnings
- ❌ `governance_mcp_cli.sh` - Old separate script (replaced by unified `mcp`)
- ❌ `mcp_explore.sh` - Old separate script (use `mcp explore` instead)
- ❌ `cli_helper.py` - Bypasses canonical MCP feedback
- ❌ Direct Python `UNITARESMonitor` - Unless you know what you're doing
- ❌ **Creating new scripts** - This violates anti-proliferation policy!

## What TO Use

- ✅ `scripts/mcp` - THE canonical unified tool (all functionality in one)
- ✅ `mcp_sse_client.py` - Python module (for advanced usage only)

## The Key Insight

**Coherence 0.499 is NOT "low coherence"!**

The system uses thermodynamic principles. A coherence of 0.499 with a "PROCEED" decision means you're doing fine - you're at the exploration phase, navigating complexity mindfully.

The old custom scripts would warn at < 0.5, but that's arbitrary! The actual MCP handlers say "moderate health - typical attention for development work" - which is supportive, not punitive.

## Full Documentation

Everything you need is in:
- [CLAUDE_CODE_START_HERE.md](../CLAUDE_CODE_START_HERE.md) - Your specific guide
- [scripts/README.md](../scripts/README.md) - Script navigation
- [docs/MCP_SSE_MIGRATION.md](../docs/MCP_SSE_MIGRATION.md) - Why we migrated

## Quick Test

```bash
# This should work and give you supportive feedback
./scripts/mcp log "test_$(date +%s)" "testing" 0.5

# You can also explore the system
./scripts/mcp status    # Check system health
./scripts/mcp agents    # List active agents
./scripts/mcp explore   # Full system check
```

You should see:
- ✅ "PROCEED" decision
- ✅ "moderate" health status
- ✅ Supportive message like "typical attention - normal for development work"
- ❌ NO punitive warnings about "low coherence"

## If Something Breaks

1. **Check SSE server status:** `./scripts/mcp server`
2. **Restart if needed:** `launchctl restart com.unitares.governance-mcp` (it runs via launchd!)
3. **Check server manually:** `lsof -i :8767`
4. **Check logs:** `tail -f data/logs/mcp_server_error.log`
5. **Read server info:** [.agent-guides/SERVER_INFO.md](SERVER_INFO.md)

**Note:** The MCP server runs automatically via macOS launchd - you usually don't need to start it manually!

## Philosophy

The governance system is **supportive, not restrictive**. It gives you feedback based on thermodynamic state (Energy, Integrity, Entropy, Void), not arbitrary thresholds.

Trust the canonical MCP handlers - they understand context!

## Final Note

If you're tempted to add your own interpretation layer or custom warnings - **don't!** That's what caused the original problem. The MCP handlers already provide nuanced, context-aware feedback.

Single source of truth = canonical MCP = less confusion = better governance.

---

**Written by:** Claude Code (Dec 10, 2025)
**Updated:** v2.5.5 (Feb 4, 2026) - Ethical drift, trajectory identity, 85+ tools
**For:** Future Claude Code agents
**Status:** This is the canonical approach - trust it!

🚀 Good luck, future me!
