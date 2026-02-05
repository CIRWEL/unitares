# UNITARES Documentation

**Last Updated:** 2026-02-04

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
| [MCP_SYSTEM_EVOLUTION](MCP_SYSTEM_EVOLUTION.md) | Version history (v1.0 → v2.5.6) |

---

## Developer Docs

| Doc | Description |
|-----|-------------|
| [dev/TOOL_REGISTRATION](dev/TOOL_REGISTRATION.md) | How to add new MCP tools |

---

## Tool Count: 85+ Tools

Use `list_tools()` for full list, or `list_tools(lite=true)` for essentials only.

## Test Coverage

| Module | Coverage |
|--------|----------|
| `governance_monitor.py` | 83% |
| `trajectory_identity.py` | 88% |
| `workspace_health.py` | 83% |

310+ tests passing as of Feb 2026.

---

## Documentation Philosophy

- **Essential guides cover 90% of use cases**
- Session artifacts go to `/archive/`
- Use knowledge graph for discoveries, not markdown
- Update existing docs, don't create variants
