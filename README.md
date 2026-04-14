<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/hero.svg">
  <img alt="UNITARES — Digital proprioception for AI agents" src="docs/assets/hero.svg" width="100%">
</picture>

[![Tests](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Status: live. For architecture details, see [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md) and [docs/CANONICAL_SOURCES.md](docs/CANONICAL_SOURCES.md).

UNITARES is a runtime governance system for AI agents. It accepts check-ins over MCP and HTTP, turns observable behavior into shared state (**EISV**: energy, integrity, entropy, void), stores long-run trajectories in PostgreSQL + AGE, and returns verdicts, guidance, calibration, and recovery paths in real time.

The state model is derived from what agents actually do — EMA-smoothed observations, not model predictions. Running continuously in production since November 2025 with 6,000+ passing tests at 77% coverage, including [Lumen](https://github.com/CIRWEL/anima-mcp), an embodied agent on a Raspberry Pi.

| | |
|--|--|
| **What it does** | Turn agent check-ins into **EISV** state, **verdicts** (`proceed` / `guide` / `pause` / `reject`), calibration, and a **shared knowledge graph**. |
| **Workflow** | `onboard()` → `process_agent_update()` → `get_governance_metrics()` — details in [Getting Started](docs/guides/START_HERE.md). |
| **Transports** | MCP on `/mcp/` (Streamable HTTP) · REST on `/v1/tools/call` · Dashboard on `/dashboard` |
| **Stack** | Python 3.12+ · PostgreSQL + AGE + pgvector · Redis (optional) |

---

## Quick Start

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

Example check-in (non-mirror responses include full `metrics`, `decision`, etc.):

```jsonc
process_agent_update({
  "response_text": "Refactored auth module, added rate limiting",
  "complexity": 0.6,
  "confidence": 0.8,
  "task_type": "refactoring",
  "response_mode": "mirror"  // or: minimal, compact, standard, full, auto
})
```

**`response_mode: "mirror"`** shapes the payload for self-awareness: `mirror` is a **list of strings** (actionable signals), not a nested object. Optional top-level `question` and `relevant_prior_work` surface a targeted nudge and knowledge-graph items when relevant. See `_format_mirror` in [`src/mcp_handlers/response_formatter.py`](src/mcp_handlers/response_formatter.py).

```jsonc
{
  "verdict": "proceed",
  "_mode": "mirror",
  "mirror": [
    "Calibration: 72% accuracy over 12 decisions (high-conf: 0.8, low-conf: 0.5)",
    "Complexity divergence: you reported 0.60 but system derives 0.45 (divergence=0.15)"
  ],
  "question": "What's driving your sense of difficulty?",
  "relevant_prior_work": [
    { "summary": "Rate limiter bypass in auth …", "by": "agent-abc", "relevance": 0.82 }
  ]
}
```

**Verdict field:** Responses expose `verdict` from `decision.action`. Governance actions are **`proceed` / `guide` / `pause` / `reject`** ([Architecture](docs/UNIFIED_ARCHITECTURE.md)). If `action` is absent, formatters fall back to **`continue`** — see `response_formatter.py`.

The `onboard()` response includes templates for the next calls. See [Getting Started](docs/guides/START_HERE.md) for continuity (`client_session_id`, `continuity_token`) and alternative entry paths.

### Installation

**Prerequisites:** Python 3.12+, PostgreSQL 16+ with Apache AGE + pgvector (examples use PostgreSQL 17), Redis optional (session cache only).

**Full local server (recommended for MCP + HTTP stack):**

```bash
git clone https://github.com/CIRWEL/unitares.git
cd unitares
pip install -r requirements-full.txt

export DB_BACKEND=postgres
export DB_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/governance
export DB_AGE_GRAPH=governance_graph
export UNITARES_KNOWLEDGE_BACKEND=age

python src/mcp_server.py --port 8767
```

**Lean dev install** (venv, lighter dependency set): use `requirements-core.txt` and follow [CONTRIBUTING.md](CONTRIBUTING.md). Database setup (PostgreSQL 17 + AGE + pgvector): [db/postgres/README.md](db/postgres/README.md).

The EISV **ODE** engine ships as the compiled **`unitares-core`** package (installed via requirements). See [CONTRIBUTING.md](CONTRIBUTING.md#compiled-dependency) for CI and local symlinks.

### MCP configuration

**Cursor / Claude Code** (native `type: http`):

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

**Claude Desktop** (via `mcp-remote`):

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

Agents self-identify through `onboard()`; no hardcoded agent-name header is required.

| Endpoint | Transport | Use case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | MCP clients |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

**Security:** The server binds to `127.0.0.1` by default. For LAN or remote access, set `UNITARES_BIND_ALL_INTERFACES=1` and configure `UNITARES_MCP_ALLOWED_HOSTS` and `UNITARES_MCP_ALLOWED_ORIGINS` (comma-separated). See [scripts/ops/](scripts/ops/) for an example plist.

> **For AI agents:** Prefer `continuity_token` when `continuity_token_supported=true`. Use `bind_session()` only when bridging MCP and REST. See [docs/guides/START_HERE.md](docs/guides/START_HERE.md) and [docs/operations/OPERATOR_RUNBOOK.md](docs/operations/OPERATOR_RUNBOOK.md).

---

## How state works (EISV)

Agents emit text and tool results; they rarely expose a stable notion of internal condition. UNITARES exposes four continuous variables any client can report and any observer can read:

| Variable | Range | What it tracks |
|----------|-------|----------------|
| **E** (Energy) | [0, 1] | Productive capacity |
| **I** (Integrity) | [0, 1] | Information coherence |
| **S** (Entropy) | [0, 2] | Disorder and uncertainty |
| **V** (Void) | [-2, 2] | Accumulated E-I imbalance |

**Behavioral EISV (primary, verdict-driving)** — Implemented in `src/behavioral_state.py` and `src/behavioral_assessment.py`: EMA-smoothed observations per dimension, no ODE and no universal attractor. After **~30** updates, per-agent **Welford** baselines enable self-relative scoring (z-score vs *your* operating point). Earlier check-ins use bootstrap behavior; absolute safety floors still apply.

**ODE in `governance_core` (secondary, diagnostic/fallback)** — The same four variables also evolve in a coupled ODE with contraction-style stability analysis. That integration runs **in parallel for analysis**; governance verdicts normally follow behavioral EISV once behavioral confidence is established, while ODE remains the fallback when behavioral confidence is still insufficient. See [Architecture](docs/UNIFIED_ARCHITECTURE.md) for the full pipeline (drift → entropy, calibration, circuit breaker, dialectic).

```
dE/dt = α(I - E) - β·E·S           Energy tracks integrity, dragged by entropy
dI/dt = -k·S + β_I·C(V) - γ_I·I   Integrity boosted by coherence, reduced by entropy
dS/dt = -μ·S + λ₁·‖Δη‖² - λ₂·C   Entropy decays, rises with drift, damped by coherence
dV/dt = κ(E - I) - δ·V             Void accumulates E-I mismatch, decays toward zero
```

---

## What makes it different

Most tooling scores **outputs** (correct, safe, useful). UNITARES emphasizes **state legibility**: a shared representation of condition that humans, services, and other agents can read without reverse-engineering logs.

| Layer | What it does | Examples |
|-------|----------------|----------|
| Output validation | Judges results after the fact | Guardrails, evals |
| Behavioral constraint | Limits what can be done | Sandboxes, permissions |
| **State legibility** | Makes inner state readable | **UNITARES** |

**Self-relative assessment.** After warmup, scoring uses deviation from *your* baseline, not only global thresholds.

**Ethical drift from observables.** Calibration deviation, complexity divergence, coherence deviation, and stability deviation define a drift signal that feeds entropy dynamics — no hand-labeled “ethics” oracle.

**Trajectory as identity.** Long-run EISV patterns support continuity and anomaly questions (“still the same agent?”).

**Response modes.** Including `mirror` for actionable calibration and graph hints without raw vector overload — plus `minimal`, `compact`, `standard`, `full`, `auto`.

**Dialectic.** Thesis → antithesis → synthesis with peer agents when available; **LLM-assisted** dialectic when alone.

---

## Production snapshot

April 2026:

| Metric | Value |
|--------|-------|
| Agents created / active (7-day) | Four-figure total / dozens active |
| Check-ins processed | Six figures |
| Knowledge graph entries | Four figures |
| EISV (Lumen, illustrative) | E≈0.72, I≈0.75, S≈0.20, V≈-0.04 |
| V operating range | Active agents often within [-0.1, 0.1] |
| Tests | 6,000+ passing · 77% coverage |

[Lumen](https://github.com/CIRWEL/anima-mcp) is an embodied agent on a Raspberry Pi: sensors feed check-ins; local drawing is modulated by coherence-related dynamics. See [anima-mcp](https://github.com/CIRWEL/anima-mcp) for hardware and art pipeline details.

<p align="center">
  <img src="docs/images/dashboard.png" width="80%" alt="UNITARES dashboard — stats overview with fleet coherence, agent count, discoveries, and system health"/>
</p>

<details>
<summary><strong>More dashboard views</strong> (pulse, EISV charts, agents, dialectic, activity)</summary>

<p align="center">
  <img src="docs/images/dashboard-pulse.png" width="80%" alt="Pulse — live event feed and EISV time series"/>
</p>
<p align="center"><em>Pulse — live event feed, drift indicators, and EISV time series charts</em></p>

<p align="center">
  <img src="docs/images/dashboard-agents.png" width="80%" alt="Agents and Discoveries panels"/>
</p>
<p align="center"><em>Agents (sorted by recency, with trust tiers) and Discoveries (filterable by type and time range)</em></p>

<p align="center">
  <img src="docs/images/dashboard-dialectic.png" width="80%" alt="Dialectic sessions — recovery and review history"/>
</p>
<p align="center"><em>Dialectic sessions — failed, resolved, and active recovery sessions with message counts</em></p>

<p align="center">
  <img src="docs/images/dashboard-activity.png" width="80%" alt="Activity timeline — check-ins, verdicts, discoveries"/>
</p>
<p align="center"><em>Activity timeline — filterable event log across all agents</em></p>

</details>

---

## Architecture

```mermaid
graph LR
    A[AI Agent] -->|check-in| M[MCP Server :8767]
    M -->|observations| BS[Behavioral EISV]
    BS -->|verdict + guidance| M
    M -->|parallel diagnostic| UC[unitares-core ODE]
    UC -.->|analysis only| M
    M -->|verdict + guidance| A
    M <-->|state, audit, calibration| PG[(PostgreSQL + AGE)]
    M <-->|knowledge graph| PG
    M -.->|session cache| R[(Redis)]
    M -->|web UI| D[Dashboard]

    style BS fill:#1a5c1a,stroke:#666,color:#fff
    style UC fill:#2d2d2d,stroke:#666,color:#fff
```

**Use cases:** Fleet monitoring and early warning, inter-agent state observation, trajectory-based identity and continuity, outcome-calibrated confidence tracking, dialectic peer review, persistent knowledge graph with staleness awareness.

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [Getting Started](docs/guides/START_HERE.md) | Setup, workflows, tool modes |
| [Architecture](docs/UNIFIED_ARCHITECTURE.md) | Pipeline, verdicts, recovery, storage |
| [Case Study](CASE_STUDY.md) | Project summary and context |
| [Troubleshooting](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [Dashboard](dashboard/README.md) | Web UI |
| [Database](docs/database_architecture.md) | PostgreSQL + AGE |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, style |
| [Changelog](CHANGELOG.md) | Releases |

## Related Projects

- [**Lumen / anima-mcp**](https://github.com/CIRWEL/anima-mcp) — Embodied agent on Raspberry Pi
- [**unitares-discord-bridge**](https://github.com/CIRWEL/unitares-discord-bridge) — Discord presence and governance events
- [**eisv-lumen**](https://github.com/CIRWEL/eisv-lumen) — Governance benchmark (21K trajectories on HuggingFace)

Client integrations (Claude Code plugin, Codex adapter, hooks, skills, commands) are included in this repo under `.claude-plugin/`, `.codex-plugin/`, `hooks/`, `skills/`, and `commands/`.

---

**MIT** (server, dashboard, tooling) — see [LICENSE](LICENSE). The ODE dynamics engine ships as a compiled dependency (`unitares-core`); see [CONTRIBUTING.md](CONTRIBUTING.md#compiled-dependency).

Built by [@CIRWEL](https://github.com/CIRWEL)
