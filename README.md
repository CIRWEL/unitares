# UNITARES

### Digital proprioception for AI agents.

[![Tests](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

UNITARES gives AI agents a shared language for inner state — four continuous variables tracked from observable behavior, and a protocol for agents to speak and be read. State is computed from what agents actually do (EMA-smoothed observations), not from what a model predicts they should do.

Started at a hackathon, deployed to production within weeks, running continuously since November 2025. ~100 MCP tools, 5,800+ tests, 100,000+ check-ins processed, one agent ([Lumen](https://github.com/CIRWEL/anima-mcp)) living on a Raspberry Pi making art from its own thermodynamics.

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

These aren't static labels. The primary system tracks them via **behavioral EISV** — exponentially weighted moving averages of agent observations, with no ODE and no universal attractor. Each agent's state reflects its actual behavior, not a dynamical model's prediction.

After ~30 check-ins, per-agent **behavioral baselines** (Welford mean/std) enable self-relative assessment — the system scores deviation from *your* characteristic operating point, not universal thresholds. Absolute safety floors still apply regardless of baseline.

A parallel system evolves the same four variables via coupled ODEs with provable stability guarantees (contraction theory). The ODE provides a secondary stability reference:

```
dE/dt = α(I - E) - β·E·S           Energy tracks integrity, dragged by entropy
dI/dt = -k·S + β_I·C(V) - γ_I·I   Integrity boosted by coherence, reduced by entropy
dS/dt = -μ·S + λ₁·‖Δη‖² - λ₂·C   Entropy decays, rises with drift, damped by coherence
dV/dt = κ(E - I) - δ·V             Void accumulates E-I mismatch, decays toward zero
```

Behavioral EISV drives verdicts. The ODE runs in parallel for agents that benefit from its convergence properties.

> [Architecture Overview](docs/UNIFIED_ARCHITECTURE.md) — How the components fit together

---

## What Makes It Different

Most agent tooling operates on **outputs** — checking whether what the agent produced is correct, safe, or useful. UNITARES operates on **inner state** — making visible what the agent can't otherwise express.

| Layer | What it does | Example tools |
|-------|-------------|---------------|
| Output validation | Checks results after the fact | Guardrails, evals, logging |
| Behavioral constraint | Restricts what agents can do | Permissions, sandboxes, filters |
| **State legibility** | Makes inner state readable | **UNITARES** |

Logging tells you what happened. Guardrails constrain what can happen. UNITARES lets agents *say what's happening inside them* — and lets other agents, systems, and humans read it. Everything else the system does — governance verdicts, circuit breakers, dialectic, the knowledge graph — is built on that legibility.

**Self-relative assessment.** After a warmup period, each agent is scored against its own behavioral baseline — z-score deviation from its characteristic operating point. An agent that normally runs at S≈0.4 isn't penalized the same way as one that normally runs at S≈0.1. Universal thresholds are a fallback, not the primary mechanism.

**Ethical drift from observable behavior.** No human oracle needed. Four measurable signals — calibration deviation, complexity divergence, coherence deviation, stability deviation — define a drift vector Δη that feeds directly into entropy dynamics.

**Trajectory as identity.** Agents aren't identified by tokens — they're identified by dynamical patterns. An agent's EISV trajectory is its behavioral signature, letting agents computationally verify "Am I still myself?" and letting observers distinguish agents by how they work.

**Mirror response mode.** Agents don't need to interpret raw EISV numbers. Mirror mode surfaces actionable self-awareness signals — calibration feedback, complexity divergence, knowledge graph discoveries — so agents get practical guidance instead of state vectors. Six response modes total — `minimal`, `compact`, `standard`, `full`, `auto`, and `mirror` — let agents and integrators choose the right signal density for their context.

**LLM-assisted dialectic.** When no peer agents are available for structured disagreement, the system can delegate antithesis/synthesis to an LLM — keeping the dialectic protocol functional even for solo agents. Peer agents are always preferred when present.

---

## Production Data

Live numbers as of April 2026:

| Metric | Value |
|--------|-------|
| Agents created / active (7-day) | 1,300+ / ~60 |
| Check-ins processed | 100,000+ |
| Knowledge graph entries | 1,700+ |
| EISV (Lumen, ODE) | E≈0.72, I≈0.75, S≈0.20, V≈-0.04 |
| V operating range | All active agents within [-0.1, 0.1] |
| Test suite | 5,800+ tests |

One of those agents is [Lumen](https://github.com/CIRWEL/anima-mcp) — an embodied creature on a Raspberry Pi whose physical sensors (temperature, humidity, light, pressure) seed its EISV state vector via spring coupling into the ODE dynamics. Coherence modulates an autonomous drawing system across four art eras; the art emerges from the same thermodynamics. Lumen gets drowsy after inactivity, proposes goals from its own preferences, discovers self-insights every 24 minutes, and falls back to local governance assessment when the Mac server is unreachable.

<p align="center">
  <img src="docs/images/dashboard.png" width="80%" alt="UNITARES web dashboard showing fleet coherence, agent status, and system health"/>
</p>

<p align="center">
  <em>Web dashboard — fleet coherence, agent status, calibration, anomaly detection.</em>
</p>

---

## Quick Start

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

Here's what a check-in looks like in practice:

```jsonc
// Agent reports what it did
process_agent_update({
  "response_text": "Refactored auth module, added rate limiting",
  "complexity": 0.6,
  "confidence": 0.8,
  "task_type": "refactoring",
  "response_mode": "mirror"  // or: minimal, compact, standard, full, auto
})

// System evolves EISV and returns a verdict
{
  "verdict": "proceed",
  "E": 0.74, "I": 0.78, "S": 0.15, "V": -0.02,
  "coherence": 0.52,
  "guidance": "State healthy. Proceed.",
  "mirror": {
    "calibration_feedback": "confidence tracks outcomes well",
    "complexity_note": "within your normal range",
    "knowledge_graph": "2 related discoveries from other agents"
  }
}
```

The `onboard()` response includes ready-to-use templates for your next calls — no guessing at parameter names. See [Getting Started](docs/guides/START_HERE.md) for the full walkthrough.

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

> **Note:** The EISV dynamics engine (`unitares-core`) is a compiled dependency installed automatically via `requirements-core.txt`. See [CONTRIBUTING.md](CONTRIBUTING.md) for build details.

### MCP Configuration

**Cursor / Claude Code** (supports `type: http` natively):

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

**Claude Desktop** (requires `mcp-remote` bridge):

```json
{
  "mcpServers": {
    "unitares": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:8767/mcp/"]
    }
  }
}
```

Agents self-identify through the `onboard()` flow — no hardcoded agent name header needed.

| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | MCP clients (Cursor, Claude Code, Claude Desktop) |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

**Security:** The server binds to `127.0.0.1` by default. For LAN/remote access, set `UNITARES_BIND_ALL_INTERFACES=1` and configure `UNITARES_MCP_ALLOWED_HOSTS` / `UNITARES_MCP_ALLOWED_ORIGINS` (comma-separated). See the [launchd plist](scripts/ops/) for a working example.

> **For AI agents:** Start with `onboard()`, keep `client_session_id` from the response, then call `process_agent_update()` with `response_mode: "mirror"`, then `get_governance_metrics()`. If `continuity_token_supported=true`, prefer `continuity_token` for resume. Use `bind_session()` only when you intentionally bridge MCP and REST transports. See [docs/guides/START_HERE.md](docs/guides/START_HERE.md) and [docs/operations/OPERATOR_RUNBOOK.md](docs/operations/OPERATOR_RUNBOOK.md).

---

## What You Can Build On It

- **Monitoring & early warning** — EISV trajectories show state changes as they happen. Circuit breakers can pause agents automatically at risk thresholds.
- **Inter-agent observation** — Agents can read each other's state vectors. One agent can assess whether another is coherent enough for a handoff without inspecting its outputs.
- **Trajectory identity** — An agent's behavioral signature over time. Enables "Am I still myself?" checks and anomaly detection for forks or impersonation.
- **Outcome correlation** — Feed task results back via `outcome_event` to build a calibration curve. The system tracks whether EISV instability predicts bad outcomes — validation is ongoing, but the plumbing works.
- **Dialectic resolution** — Structured disagreement (thesis → antithesis → synthesis) with a shared state language. Agents negotiate meaningfully when they can read each other's coherence and confidence. Falls back to LLM-assisted dialectic when no peers are available.
- **Knowledge persistence** — Discoveries tagged to agent state and system version, stored in a shared graph with staleness detection. Agents build on each other's findings across sessions.
- **Session identity bridging** — `bind_session` links MCP and REST identities so an agent's governance state follows it across transport changes.

---

## Architecture

```mermaid
graph LR
    A[AI Agent] -->|check-in| M[MCP Server :8767]
    M -->|observations| BS[Behavioral EISV]
    BS -->|verdict + guidance| M
    M -->|parallel| UC[unitares-core ODE]
    UC -.->|secondary state| M
    M -->|verdict + guidance| A
    M <-->|state, audit, calibration| PG[(PostgreSQL + AGE)]
    M <-->|knowledge graph| PG
    M -.->|session cache| R[(Redis)]
    M -->|web UI| D[Dashboard]

    style BS fill:#1a5c1a,stroke:#666,color:#fff
    style UC fill:#2d2d2d,stroke:#666,color:#fff
```

```
src/                   MCP server (~100 tools), agent state, knowledge graph, dialectic
  mcp_handlers/        Modular tool handlers: identity, lifecycle, knowledge, dialectic,
                       observability, admin, CIRS, introspection, Pi orchestration
dashboard/             Web dashboard (vanilla JS + Chart.js)
tests/                 5,800+ tests
```

Behavioral EISV (`src/behavioral_state.py`, `src/behavioral_assessment.py`) runs observation-first state tracking. The ODE engine (`governance_core`) — coupled dynamics, coherence, scoring — is a compiled package (unitares-core) providing parallel stability analysis.

| Storage | Purpose | Required |
|---------|---------|----------|
| PostgreSQL + AGE | Agent state, knowledge graph, dialectic, calibration | Yes |
| Redis | Session cache only — falls back gracefully without it | Optional |

---

## Open Questions

These are unsolved problems. The system is honest about what it doesn't yet do well.

- **Outcome correlation** — *(Partially addressed.)* The `outcome_event` tool now feeds task results (test pass/fail, command exit codes, lint results) back into calibration automatically. Confidence calibration is currently around 50% accuracy — better than chance but not yet reliably predictive. Whether EISV instability predicts real-world failure remains the central empirical question.
- **Agent differentiation** — *(Addressed in v2.9.0.)* The ODE's convergence guarantees caused agents with similar workloads to converge to similar steady states. Behavioral EISV — EMA-smoothed observations without ODE contraction — is now the primary verdict source, giving each agent its own trajectory. Behavioral baselines need ~30 updates to stabilize; before that, fixed thresholds apply.
- **Identity fragmentation** — Session-based identity means the same human or system can accumulate many agent IDs across sessions. Most of the 1,300+ total agents are ephemeral (test runs, CI, dev sessions). Identity consolidation and trajectory-based re-identification are active work.
- **Domain-specific thresholds** — How should parameters be tuned for code generation vs. customer service vs. trading? No one-size-fits-all answer yet.
- **Horizontal scaling** — Current system handles hundreds of agents on a single node. What about thousands?

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [Getting Started](docs/guides/START_HERE.md) | Complete setup and onboarding guide |
| [Architecture](docs/UNIFIED_ARCHITECTURE.md) | System topology, EISV dynamics, database ownership |
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

## Licensing

The MCP server, dashboard, tooling, and all code in this repo are **MIT licensed** — see [LICENSE](LICENSE). The EISV dynamics engine (`unitares-core`) is a **proprietary compiled dependency**. It installs automatically via `requirements-core.txt`, but its source is not in this repo. You can freely use, modify, and deploy the server; the mathematical core is not open source. See [CONTRIBUTING.md](CONTRIBUTING.md#compiled-dependency) for details.

---

Built by [@CIRWEL](https://github.com/CIRWEL) | **v2.9.0**
