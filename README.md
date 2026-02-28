# UNITARES

### Digital proprioception for AI agents.

[![Tests](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AI agents today have no body sense. They can't tell if they're drifting, looping, or degrading until they crash. UNITARES gives agents continuous awareness of their own state using coupled differential equations with [provable stability guarantees](governance_core/README.md).

We've validated the framework on **903 agents over 69 days** (198K audit events). The [paper](papers/unitares-v5/) has the full analysis; this repo is the production implementation.

> *"The Self isn't coded; it accretes like a pearl."*

---

## The Idea

Agents don't fail suddenly. They **drift** toward failure. Logs tell you what happened; alerts tell you something broke. Neither tells you it's *happening*.

UNITARES models agent state as a thermodynamic system with four continuous variables:

| Variable | Range | What it tracks |
|----------|-------|----------------|
| **E** (Energy) | [0, 1] | Productive capacity |
| **I** (Integrity) | [0, 1] | Information coherence |
| **S** (Entropy) | [0, 2] | Disorder and uncertainty |
| **V** (Void) | [-2, 2] | Accumulated E-I imbalance |

These evolve via coupled ODEs:

```
dE/dt = α(I - E) - β·E·S           Energy tracks integrity, dragged by entropy
dI/dt = -k·S + β_I·C(V) - γ_I·I   Integrity boosted by coherence, reduced by entropy
dS/dt = -μ·S + λ₁·‖Δη‖² - λ₂·C   Entropy decays, rises with drift, damped by coherence
dV/dt = κ(E - I) - δ·V             Void accumulates E-I mismatch, decays toward zero
```

The key insight: **coherence C(V)** creates nonlinear feedback that stabilizes the system. We prove global exponential convergence via contraction theory ([Theorem 3.2](papers/unitares-v5/)).

Twenty minutes before an agent fails, you see it trending. Intervene, or let the circuit breaker pause it automatically.

> [Why UNITARES?](docs/WHY.md) — Concrete failure modes this solves

---

## Three Novel Contributions

**1. Ethical drift from observable behavior.** No human oracle needed. Four measurable signals — calibration deviation, complexity divergence, coherence deviation, stability deviation — define a drift vector Δη that feeds directly into entropy dynamics. Ethics as engineering, not philosophy.

**2. Adaptive PID governance (CIRS v2).** Governance thresholds are per-agent state variables, not static config. Phase-aware reference tracking with oscillation damping. Multi-agent resonance detection prevents feedback loops between coordinated agents.

**3. Trajectory identity.** Agents aren't identified by tokens — they're identified by dynamical patterns. Grounded in enactive cognition (Varela & Thompson), this lets agents computationally verify "Am I still myself?" and detect forks, anomalies, and drift.

---

## Lumen: Embodied Proprioception

[Lumen](https://github.com/CIRWEL/anima-mcp) is an AI creature running on a Raspberry Pi with physical sensors (temperature, humidity, light, neural bands). It uses the same EISV equations to drive a drawing system — coherence directly modulates how long it can draw and how selective it is about saving.

A confused Lumen draws in short, erratic bursts. A focused Lumen draws flowing, sustained compositions. The art emerges from thermodynamics.

---

## Quick Start

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

That's it. Everything else is optional. See [Getting Started](docs/guides/GETTING_STARTED_SIMPLE.md) for the full walkthrough.

### Installation

**Prerequisites:** Python 3.11+, PostgreSQL 16+ with [AGE extension](https://github.com/apache/age), Redis (optional)

```bash
git clone https://github.com/CIRWEL/unitares.git
cd governance-mcp-v1
pip install -r requirements-core.txt

# MCP server (multi-client)
python src/mcp_server.py --port 8767

# Or stdio mode (single-client)
python src/mcp_server_std.py
```

### MCP Configuration (Cursor / Claude Desktop)

```json
{
  "mcpServers": {
    "unitares": {
      "type": "http",
      "url": "http://localhost:8767/mcp/",
      "headers": { "X-Agent-Name": "MyAgent" }
    }
  }
}
```

| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | MCP clients (Cursor, Claude Desktop) |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

> See [MCP Setup Guide](docs/guides/MCP_SETUP.md) for ngrok, curl examples, and advanced configuration.

---

## Production Validation

Deployed since December 2025. Current numbers:

| Metric | Value |
|--------|-------|
| Agents monitored | 903 |
| Deployment duration | 69 days |
| Audit events | 198,333 |
| EISV equilibrium | E=0.77, I=0.88, S=0.08, V=-0.03 |
| V operating range | 100% of agents within [-0.1, 0.1] |
| Dialectic sessions | 66 |
| Knowledge discoveries | 500 |
| Test suite | 5,654 tests, 80% coverage |

---

## Architecture

```
governance_core/       Pure math — ODEs, coherence, scoring (no I/O)
src/                   MCP server, agent state, knowledge graph, dialectic
dashboard/             Web dashboard (Alpine.js + htmx)
papers/                Academic paper with contraction proofs
tests/                 5,654 tests
```

| Storage | Purpose | Required |
|---------|---------|----------|
| PostgreSQL + AGE | Agent state, knowledge graph, dialectic, calibration | Yes |
| Redis | Session cache, rate limiting | Optional |

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [The Paper](papers/unitares-v5/) | Full mathematical framework with proofs |
| [Math Foundation](governance_core/README.md) | EISV dynamics, coherence, ethical drift |
| [Why UNITARES?](docs/WHY.md) | The problem this solves |
| [Getting Started](docs/guides/GETTING_STARTED_SIMPLE.md) | 3-step quickstart |
| [Full Onboarding](docs/guides/START_HERE.md) | Complete setup guide |
| [Troubleshooting](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [Dashboard](dashboard/README.md) | Web dashboard docs |
| [Database Architecture](docs/database_architecture.md) | PostgreSQL + Redis |
| [Changelog](CHANGELOG.md) | Release history |

---

## Active Research

These are open questions, not solved problems:

- **Outcome correlation** — Does EISV instability predict bad task outcomes? Early signals are promising, validation ongoing.
- **Domain-specific thresholds** — How should parameters be tuned for code generation vs. customer service vs. trading? No one-size-fits-all answer yet.
- **Horizontal scaling** — Current system handles hundreds of agents on a single node. What about thousands?

We believe in stating what works, what's promising, and what we don't know yet.

---

## Related Projects

- [**Lumen / anima-mcp**](https://github.com/CIRWEL/anima-mcp) — Embodied AI on Raspberry Pi with physical sensors and EISV-driven art
- [**unitares-discord-bridge**](https://github.com/CIRWEL/unitares-discord-bridge) — Discord bot surfacing governance events, agent presence, and Lumen state

---

Built by [@CIRWEL](https://github.com/CIRWEL) | MIT License — see [LICENSE](LICENSE) | **v2.8.0**
