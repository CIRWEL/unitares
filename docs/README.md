# UNITARES Documentation

**Last Updated:** 2026-02-06

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
| [MCP_SYSTEM_EVOLUTION](MCP_SYSTEM_EVOLUTION.md) | Version history (v1.0 → v2.6.3) |

---

## Developer Docs

| Doc | Description |
|-----|-------------|
| [dev/TOOL_REGISTRATION](dev/TOOL_REGISTRATION.md) | How to add new MCP tools |

---

## Tool Count: 30 Registered Tools

v2.6.2 has 30 tools + aliases (status, list_agents, observe_agent, checkin, etc.). Use `list_tools()` or read [SKILL.md](../skills/unitares-governance/SKILL.md).

## Test Coverage

| Module | Coverage |
|--------|----------|
| `governance_monitor.py` | 83% |
| `trajectory_identity.py` | 88% |
| `workspace_health.py` | 83% |
| **Overall** | **49%** |

2,602 tests passing as of v2.6.3 (Feb 2026).

---

## Project Structure

```
governance-mcp-v1/
├── src/
│   ├── governance_monitor.py   # Core EISV dynamics
│   ├── cirs.py                 # Oscillation detection
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
│   └── scoring.py              # Φ objective, verdicts
├── dashboard/                  # Web dashboard (HTML/CSS/JS)
├── skills/                     # SKILL.md for agent onboarding
├── docs/                       # Documentation
├── data/                       # Runtime data (agents/, knowledge/)
└── tests/                      # 2,602 tests, 49% coverage
```

---

## Documentation Philosophy

- **Essential guides cover 90% of use cases**
- Session artifacts go to `/archive/`
- Use knowledge graph for discoveries, not markdown
- Update existing docs, don't create variants
