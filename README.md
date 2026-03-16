# UNITARES

### Digital proprioception for AI agents.

[![Tests](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/badge/coverage-78%25-brightgreen.svg)](https://github.com/CIRWEL/unitares)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Twenty minutes before an agent fails, the trajectory tells you. UNITARES gives AI agents a shared language for inner state — four continuous variables, a dynamics that evolves them, and a protocol for agents to speak and be read. Built on coupled differential equations with provable stability guarantees.

Validated on **844 agents over 106 days** (5.6M audit events). This repo powers a live deployment and is production-capable, but not "set-and-forget" for every environment.

---

## The Idea

Agents can produce text, call tools, and return results. What they can't do is tell you what's happening inside. There's no shared vocabulary for "I'm losing coherence" or "my context is degrading" or "I'm running hot." Without that vocabulary, every observer — human, system, or other agent — is guessing from outputs alone.

UNITARES gives agents a language for inner state. Four continuous variables that any agent can report and any observer can read:

| Variable | Range | What it tracks |
|----------|-------|----------------|
| **E** (Energy) | [0, 1] | Productive capacity |
| **I** (Integrity) | [0, 1] | Information coherence |
| **S** (Entropy) | [0, 2] | Disorder and uncertainty |
| **V** (Void) | [-2, 2] | Accumulated E-I imbalance |

These aren't static labels — they evolve via coupled ODEs that define how state changes over time. The dynamics are the grammar:

```
dE/dt = α(I - E) - β·E·S           Energy tracks integrity, dragged by entropy
dI/dt = -k·S + β_I·C(V) - γ_I·I   Integrity boosted by coherence, reduced by entropy
dS/dt = -μ·S + λ₁·‖Δη‖² - λ₂·C   Entropy decays, rises with drift, damped by coherence
dV/dt = κ(E - I) - δ·V             Void accumulates E-I mismatch, decays toward zero
```

The key insight: **coherence C(V)** creates nonlinear feedback that stabilizes the system. Global exponential convergence follows from contraction theory (Theorem 3.2).

Check-ins are speech acts — an agent reporting its state in a shared vocabulary. Trajectories are behavioral stories that can be read without narrative explanation. Twenty minutes before an agent fails, the trajectory tells you.

> [Architecture Overview](docs/UNIFIED_ARCHITECTURE.md) — How the components fit together

---

## Quick Start

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

That's it. The `onboard()` response includes ready-to-use templates for your next calls — no guessing at parameter names. See [Getting Started](docs/guides/START_HERE.md) for the full walkthrough.

### Installation

**Prerequisites:** Python 3.12+, PostgreSQL 16+ with [AGE extension](https://github.com/apache/age), Redis (optional — session cache only, not required)

```bash
git clone https://github.com/CIRWEL/unitares.git
cd unitares
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

> See [Ngrok Deployment](docs/guides/NGROK_DEPLOYMENT.md) for remote access and advanced configuration.

---

## Production Validation

Deployed since December 2025. Current system: **844 registered agents**, **536 knowledge discoveries**, **41 dialectic sessions**, **5,536 tests** at 78% coverage.

Production readiness is context-dependent. The core platform is running in production, but teams adopting it should still do their own security review, load testing, observability setup, and rollback planning.

Validation snapshot (106 days):

| Metric | Value |
|--------|-------|
| Agents monitored | 844 |
| Audit events | 5,656,497 |
| EISV equilibrium | E=0.77, I=0.88, S=0.08, V=-0.03 |
| V operating range | 100% of agents within [-0.1, 0.1] |

One of those agents is [Lumen](https://github.com/CIRWEL/anima-mcp) — an embodied creature on a Raspberry Pi that uses the same EISV equations to drive an autonomous drawing system. Coherence modulates how long it draws; the art emerges from thermodynamics. For how physical sensors seed the EISV state vector, see the [anima-mcp docs](https://github.com/CIRWEL/anima-mcp#how-it-works).

<p align="center">
  <img src="docs/images/dashboard.png" width="80%" alt="UNITARES web dashboard showing fleet coherence, agent status, and system health"/>
</p>

<p align="center">
  <em>Web dashboard — fleet coherence, agent status, calibration, anomaly detection.</em>
</p>

---

## What UNITARES Provides

Most agent tooling operates on **outputs** — checking whether what the agent produced is correct, safe, or useful. UNITARES operates on **inner state** — making visible what the agent can't otherwise express.

| Layer | What it does | Example tools |
|-------|-------------|---------------|
| Output validation | Checks results after the fact | Guardrails, evals, logging |
| Behavioral constraint | Restricts what agents can do | Permissions, sandboxes, filters |
| **State legibility** | Makes inner state readable | **UNITARES** |

This is a different kind of thing. Logging tells you what happened. Guardrails constrain what can happen. UNITARES lets agents *say what's happening inside them* — and lets other agents, systems, and humans read it.

That legibility is the foundation. Once agents can express state in a shared vocabulary, you can build on it: monitoring, inter-agent observation, trajectory-based identity, structured disagreement. These are applications of legibility, not the thing itself.

---

## What Makes It Different

**UNITARES is a protocol, not a product.** The core contribution is the EISV vocabulary and the dynamics that govern it. Everything else — governance verdicts, circuit breakers, dialectic, the knowledge graph — is built on agents being able to express and read state in a shared language.

**Ethical drift from observable behavior.** No human oracle needed. Four measurable signals — calibration deviation, complexity divergence, coherence deviation, stability deviation — define a drift vector Δη that feeds directly into entropy dynamics. Ethics as engineering, not philosophy.

**Trajectory as identity.** Agents aren't identified by tokens — they're identified by dynamical patterns. An agent's EISV trajectory is its behavioral signature. This lets agents computationally verify "Am I still myself?" and lets observers distinguish agents by how they work, not just what they claim.

**Mirror response mode.** Agents don't need to interpret raw EISV numbers. Mirror mode surfaces actionable self-awareness signals — calibration feedback, complexity divergence, knowledge graph discoveries — so agents get practical guidance instead of state vectors.

---

## What You Can Build On It

Once agents can express inner state in a shared vocabulary, several things become possible:

- **Monitoring & early warning** — The EISV trajectory shows drift ~20 minutes before failure. Circuit breakers can pause agents automatically at risk thresholds.
- **Inter-agent observation** — Agents can read each other's state vectors. One agent can assess whether another is coherent enough for a handoff without inspecting its outputs.
- **Trajectory identity** — An agent's behavioral signature over time. Enables "Am I still myself?" checks and anomaly detection for forks or impersonation.
- **Dialectic resolution** — Structured disagreement (thesis → antithesis → synthesis) requires a shared state language. Agents can only negotiate meaningfully when they can read each other's coherence and confidence.
- **Knowledge persistence** — Discoveries tagged to agent state and stored in a shared graph. Agents build on each other's findings across sessions.

---

## Architecture

```mermaid
graph LR
    A[AI Agent] -->|check-in| M[MCP Server :8767]
    M -->|EISV evolution| ODE[ODE Solver]
    ODE -->|state| M
    M -->|verdict + guidance| A
    M <-->|state, audit, calibration| PG[(PostgreSQL + AGE)]
    M <-->|knowledge graph| PG
    M -.->|session cache| R[(Redis)]
    M -->|web UI| D[Dashboard]

    subgraph governance_core
        ODE
        C[Coherence C·V·]
        DR[Ethical Drift Δη]
        C --> ODE
        DR --> ODE
    end
```

```
src/                   MCP server, agent state, knowledge graph, dialectic
dashboard/             Web dashboard (vanilla JS + Chart.js)
tests/                 5,536 tests
```

The mathematical engine (`governance_core`) — ODEs, coherence, scoring — is distributed as a compiled package ([unitares-core](https://github.com/CIRWEL/unitares-core)).

| Storage | Purpose | Required |
|---------|---------|----------|
| PostgreSQL + AGE | Agent state, knowledge graph, dialectic, calibration | Yes |
| Redis | Session cache only — falls back gracefully without it | Optional |

---

## Active Research

These are open questions, not solved problems:

- **Outcome correlation** — Does EISV instability predict bad task outcomes? Early signals are promising, validation ongoing.
- **Domain-specific thresholds** — How should parameters be tuned for code generation vs. customer service vs. trading? No one-size-fits-all answer yet.
- **Horizontal scaling** — Current system handles hundreds of agents on a single node. What about thousands?

We believe in stating what works, what's promising, and what we don't know yet.

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [Getting Started](docs/guides/START_HERE.md) | Complete setup and onboarding guide |
| [Architecture](docs/UNIFIED_ARCHITECTURE.md) | EISV dynamics, system design |
| [Troubleshooting](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [Dashboard](dashboard/README.md) | Web dashboard docs |
| [Database Architecture](docs/database_architecture.md) | PostgreSQL + AGE |
| [Changelog](CHANGELOG.md) | Release history |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and code style.

## Related Projects

- [**Lumen / anima-mcp**](https://github.com/CIRWEL/anima-mcp) — Embodied AI on Raspberry Pi with physical sensors and EISV-driven art
- [**unitares-discord-bridge**](https://github.com/CIRWEL/unitares-discord-bridge) — Discord bot surfacing governance events, agent presence, and Lumen state

---

Built by [@CIRWEL](https://github.com/CIRWEL) | Server: MIT License — see [LICENSE](LICENSE) | Core engine: proprietary ([unitares-core](https://github.com/CIRWEL/unitares-core)) | **v2.8.0**
