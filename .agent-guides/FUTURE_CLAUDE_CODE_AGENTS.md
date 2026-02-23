# Hey Future Claude Code!

If you're reading this, you're probably wondering how to use the governance system. **It's simple!**

## TL;DR

```
1. onboard()                    -> Get your identity
2. process_agent_update()       -> Log your work
3. get_governance_metrics()     -> Check your state
```

That's it. Read the SKILL.md at `~/.claude/skills/unitares-governance/SKILL.md` for concepts.

**IMPORTANT:** Use ONLY `./scripts/mcp` for CLI operations - do not create new scripts! We have a strict anti-proliferation policy.

## Database: ONE PostgreSQL, That's It

- **Docker container `postgres-age`** on port **5432** - this is the only database
- PostgreSQL + AGE (graph) + pgvector (embeddings)
- Redis on port 6379 for session cache (optional)
- **NO SQLite on Mac. NO Homebrew PostgreSQL. NO dual backends.**
- Homebrew PostgreSQL (port 5433) is a separate violin auction project - DO NOT TOUCH

## What NOT to Do

- Do NOT create new scripts (use `./scripts/mcp`)
- Do NOT add custom interpretation layers with arbitrary thresholds
- Do NOT connect to port 5433 or any Homebrew PostgreSQL
- Do NOT reference SQLite, `governance.db`, or dual data stores
- Do NOT use port 8765 or `/sse` endpoint (deprecated)

## What TO Use

- `./scripts/mcp` - THE canonical unified CLI tool
- Port **8767** with `/mcp/` endpoint for MCP connections
- Port **8767** with `/health` for health checks

## The Key Insight

**Coherence 0.499 is NOT "low coherence"!**

The system uses thermodynamic principles. A coherence of 0.499 with a "PROCEED" decision means you're doing fine - you're at the exploration phase, navigating complexity mindfully. The actual MCP handlers say "moderate health - typical attention for development work" - which is supportive, not punitive.

## If Something Breaks

1. **Check health:** `curl http://localhost:8767/health | jq`
2. **Restart:** `launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist && launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist`
3. **Check port:** `lsof -i :8767`
4. **Check logs:** `tail -f /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server_error.log`

The MCP server runs automatically via macOS launchd - you usually don't need to start it manually.

## Philosophy

The governance system is **supportive, not restrictive**. It gives you feedback based on thermodynamic state (Energy, Integrity, Entropy, Void), not arbitrary thresholds. Trust the canonical MCP handlers.

---

**Updated:** Feb 22, 2026
**For:** Future Claude Code agents
