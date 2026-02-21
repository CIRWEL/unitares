# UNITARES Documentation

**Last Updated:** 2026-02-20

---

## Quick Start

| You are... | Start here |
|------------|------------|
| **New agent** | [SKILL.md](../skills/unitares-governance/SKILL.md) — Framework concepts + tool reference |
| **Developer** | [TOOL_REGISTRATION](dev/TOOL_REGISTRATION.md) — How to add new MCP tools |

---

## Reference Docs

| Doc | Description |
|-----|-------------|
| [governance_core/README](../governance_core/README.md) | Mathematical foundation (EISV dynamics) |
| `list_tools()` | Tool catalog (use MCP tool) |
| [CIRCUIT_BREAKER_DIALECTIC](CIRCUIT_BREAKER_DIALECTIC.md) | Circuit breaker + recovery protocol |
| [database_architecture](database_architecture.md) | PostgreSQL + Redis architecture |
| [MCP_SYSTEM_EVOLUTION](MCP_SYSTEM_EVOLUTION.md) | Version history (v1.0 → current) |

---

## Developer Docs

| Doc | Description |
|-----|-------------|
| [dev/TOOL_REGISTRATION](dev/TOOL_REGISTRATION.md) | How to add new MCP tools |

---

## Tool Count: 30 Registered Tools

30 registered tools + aliases (status, list_agents, observe_agent, checkin, etc.). See [SKILL.md](../skills/unitares-governance/SKILL.md) for the full tool reference.

## Test Coverage

6,407 tests passing with **80% overall coverage** as of Feb 2026.

---

## Project Structure

```
governance-mcp-v1/
├── src/
│   ├── governance_monitor.py   # Core EISV dynamics
│   ├── cirs.py                 # Oscillation detection (legacy)
│   │   └── cirs_protocol.py   # CIRS v2 multi-agent protocol + auto-emit hooks
│   ├── mcp_server.py           # HTTP server (multi-client)
│   ├── mcp_server_std.py       # Stdio server (single-client)
│   ├── mcp_handlers/           # Tool implementations
│   │   ├── decorators.py       # @mcp_tool, ToolDefinition, action_router()
│   │   ├── middleware.py       # 8-step dispatch pipeline (identity, alias, rate limit, etc.)
│   │   ├── consolidated.py     # 7 consolidated tools via action_router()
│   │   ├── response_formatter.py # Response mode filtering (auto/minimal/compact/standard/full)
│   │   ├── identity_v2.py      # Identity resolution (4-path: Redis→PG→Name→Create)
│   │   ├── core.py             # process_agent_update, metrics
│   │   ├── dialectic.py        # Dialectic peer review
│   │   ├── observability.py    # Observe/compare/anomaly handlers
│   │   └── knowledge_graph.py  # Knowledge storage & search
│   ├── db/                     # Database backends
│   │   └── postgres_backend.py # PostgreSQL (primary)
│   ├── cache/                  # Redis client, rate limiter
│   └── storage/
│       └── knowledge_graph_age.py  # AGE graph database
├── governance_core/            # Canonical math (Phase-3)
│   ├── dynamics.py             # Differential equations
│   ├── coherence.py            # C(V,Θ) function
│   ├── ethical_drift.py        # Δη vector computation
│   ├── scoring.py              # Φ objective, verdicts
│   └── adaptive_governor.py    # CIRS v2 PID controller (oscillation → neighbor pressure)
├── dashboard/                  # Web dashboard (HTML/CSS/JS)
├── skills/                     # SKILL.md for agent onboarding
├── docs/                       # Documentation
├── data/                       # Runtime data (agents/, knowledge/)
└── tests/                      # 6,407 tests, 80% coverage
```

---

## Documentation Philosophy

- **Essential guides cover 90% of use cases**
- Session artifacts go to `/archive/`
- Use knowledge graph for discoveries, not markdown
- Update existing docs, don't create variants
