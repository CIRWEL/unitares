# UNITARES Documentation

**Last Updated:** 2026-02-05

---

## Quick Start

| You are... | Start here |
|------------|------------|
| **New agent** | [GETTING_STARTED_SIMPLE](guides/GETTING_STARTED_SIMPLE.md) — 3 tools, 3 steps |
| **MCP client** | [START_HERE](guides/START_HERE.md) — Full onboarding |

---

## Essential Guides

| Guide | Description |
|-------|-------------|
| [GETTING_STARTED_SIMPLE](guides/GETTING_STARTED_SIMPLE.md) | Fastest path - 3 tools |
| [START_HERE](guides/START_HERE.md) | Full onboarding guide |
| [LLM_DELEGATION](guides/LLM_DELEGATION.md) | LLM calls + dialectic recovery |
| [DEPLOYMENT](guides/DEPLOYMENT.md) | Installation & setup (includes [ngrok](guides/NGROK_DEPLOYMENT.md)) |
| [MCP_SETUP](guides/MCP_SETUP.md) | MCP client configuration |
| [TROUBLESHOOTING](guides/TROUBLESHOOTING.md) | Common issues & fixes |

---

## Reference Docs

| Doc | Description |
|-----|-------------|
| [governance_core/README](../governance_core/README.md) | Mathematical foundation (EISV dynamics) |
| `list_tools()` | Tool catalog (use MCP tool) |
| [CIRCUIT_BREAKER_DIALECTIC](CIRCUIT_BREAKER_DIALECTIC.md) | Circuit breaker + recovery protocol |
| [database_architecture](database_architecture.md) | PostgreSQL + Redis architecture |
| [MCP_SYSTEM_EVOLUTION](MCP_SYSTEM_EVOLUTION.md) | Version history (v1.0 → v2.6.0) |

---

## Developer Docs

| Doc | Description |
|-----|-------------|
| [dev/TOOL_REGISTRATION](dev/TOOL_REGISTRATION.md) | How to add new MCP tools |

---

## Tool Count: 29 Registered Tools

v2.6.0 reduced the public surface from 49 to 29 tools. Use `list_tools()` or read [SKILL.md](../skills/unitares-governance/SKILL.md).

## Test Coverage

| Module | Coverage |
|--------|----------|
| `governance_monitor.py` | 83% |
| `trajectory_identity.py` | 88% |
| `workspace_health.py` | 83% |
| **Overall** | **41%** |

1,907 tests passing as of v2.6.0 (Feb 2026).

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
│   │   ├── identity_v2.py      # Identity resolution (session→UUID)
│   │   ├── core.py             # process_agent_update, metrics
│   │   ├── dialectic.py        # Dialectic peer review
│   │   ├── consolidated.py     # Unified agent/config/calibration tools
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
└── tests/                      # 1,907 tests, 41% coverage
```

---

## Documentation Philosophy

- **Essential guides cover 90% of use cases**
- Session artifacts go to `/archive/`
- Use knowledge graph for discoveries, not markdown
- Update existing docs, don't create variants
