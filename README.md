# UNITARES Governance

[![Tests](https://github.com/CIRWEL/governance-mcp-v1-backup/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/governance-mcp-v1-backup/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Stability monitoring for multi-agent AI systems.**

UNITARES monitors AI agent behavior using continuous state variables. When agents get stuck, loop, or drift toward instability, you get early warning — not just crash alerts. Thermodynamic state modeling gives you trends, graduated responses, and physics-grounded intuition about agent health.

---

## Quick Start

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

That's it. Everything else is optional. See [Getting Started](docs/guides/GETTING_STARTED_SIMPLE.md) for the full walkthrough.

---

## Features

- **EISV state tracking** — Continuous Energy, Integrity, Entropy, Void monitoring
- **Circuit breakers** — Automatic pause when risk thresholds crossed
- **Stuck-agent detection** — Find unresponsive agents with auto-recovery
- **Oscillation detection** — Catch decision flip-flop loops (CIRS)
- **Dialectic peer review** — Structured thesis/antithesis/synthesis for dispute resolution
- **Knowledge graph** — Persistent cross-agent learning with semantic search (Apache AGE)
- **Cross-agent observability** — Compare agents, detect anomalies, aggregate metrics
- **Ethical drift tracking** — Parameter change magnitude fed into stability objective
- **Trajectory identity** — Genesis signatures, lineage comparison, anomaly detection
- **Web dashboard** — Real-time agent metrics, dialectic sessions, knowledge discoveries
- **Pi/Lumen orchestration** — Coordinate with Raspberry Pi-based embodied agents

> Outcome correlation and domain-specific threshold tuning are active research areas.

---

## How It Works

| Variable | Range | Tracks |
|----------|-------|--------|
| **E** (Energy) | [0,1] | Productive capacity |
| **I** (Integrity) | [0,1] | Information coherence |
| **S** (Entropy) | [0,1] | Disorder / uncertainty |
| **V** (Void) | [0,1] | Accumulated E-I imbalance |

```
Agent logs work → EISV update → Stability check → Decision (proceed/caution/pause) → Feedback
```

Continuous variables mean you see an agent *trending* toward trouble before it crashes. See [governance_core/README.md](governance_core/README.md) for the full mathematical framework.

---

## Installation

**Prerequisites:** Python 3.10+, PostgreSQL 16+, Redis (optional)

```bash
git clone https://github.com/CIRWEL/governance-mcp-v1-backup.git
cd governance-mcp-v1
pip install -r requirements-core.txt

# MCP server (multi-client)
python src/mcp_server.py --port 8767

# Or stdio mode (single-client)
python src/mcp_server_std.py
```

| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | MCP clients (Cursor, Claude Desktop) |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

> MCP URLs must end with `/mcp/` (trailing slash required).

| Storage | Purpose | Required |
|---------|---------|----------|
| PostgreSQL | Agent state, dialectic sessions, calibration | Yes |
| AGE extension | Knowledge graph with semantic search | Yes |
| Redis | Session cache, rate limiting | Optional |

---

## MCP Configuration

**Cursor / Claude Desktop:**
```json
{
  "mcpServers": {
    "unitares": {
      "type": "http",
      "url": "http://localhost:8767/mcp/"
    }
  }
}
```

For REST clients, include an `X-Session-ID` header to maintain identity across calls. See [MCP Setup Guide](docs/guides/MCP_SETUP.md) for ngrok, curl examples, and advanced configuration.

---

## Key Concepts

**30 registered tools** — v2.6.2 reduced the public surface from 49 to 30 tools via consolidation (`action_router`). Use `list_tools()` or read [SKILL.md](skills/unitares-governance/SKILL.md) for the full catalog.

**Three-tier identity:**

| Tier | Field | Example |
|------|-------|---------|
| UUID | `uuid` | `a1b2c3d4-...` (immutable, server-assigned) |
| agent_id | `agent_id` | `Claude_Opus_4_5_20260204` (model-based) |
| display_name | `name` | `MyAgent` (human-readable) |

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [Getting Started](docs/guides/GETTING_STARTED_SIMPLE.md) | 3-step quickstart |
| [Full Onboarding](docs/guides/START_HERE.md) | Complete setup guide |
| [Troubleshooting](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [Math Foundation](governance_core/README.md) | EISV dynamics, coherence, drift |
| [Dashboard](dashboard/README.md) | Web dashboard docs |
| [Database Architecture](docs/database_architecture.md) | PostgreSQL + Redis |
| [Changelog](CHANGELOG.md) | Release history |

---

## Testing

```bash
python -m pytest tests/ -v
```

2,602 tests, 49% coverage. Core modules: governance_monitor 83%, trajectory_identity 88%, workspace_health 83%.

---

## Roadmap

- Outcome correlation — does instability predict bad outcomes?
- Threshold tuning — domain-specific calibration
- WebSocket dashboard updates (replace polling)
- CIRS v1.0 — full multi-agent oscillation damping
- Semantic ethical drift detection
- Production hardening and horizontal scaling

See [CHANGELOG.md](CHANGELOG.md) for release history. Contributions welcome.

---

Built by [@CIRWEL](https://github.com/CIRWEL). Also building [Lumen/anima-mcp](https://github.com/CIRWEL/anima-mcp).

MIT License with Attribution — see [LICENSE](LICENSE).

**v2.6.3** | 2026-02-06
