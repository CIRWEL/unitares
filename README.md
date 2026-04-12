# UNITARES

### Digital proprioception for AI agents.

📄 **Paper**: [UNITARES: Runtime Governance for AI Agents (v3)](papers/unitares-runtime-governance-v3.pdf) — preprint, April 2026

Status: live overview. For architecture truth and code-first authority ordering, see [docs/CANONICAL_SOURCES.md](docs/CANONICAL_SOURCES.md).

[![Tests](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml/badge.svg)](https://github.com/CIRWEL/unitares/actions/workflows/tests.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

UNITARES is a runtime governance system for AI agents. It accepts check-ins over MCP and HTTP, turns observable behavior into shared state (**EISV**: energy, integrity, entropy, void), stores long-run trajectories in PostgreSQL + AGE, and returns verdicts, guidance, calibration, and recovery paths in real time.

The state model is derived from what agents actually do (EMA-smoothed observations), not from what a model predicts they should do. As a portfolio artifact, this repo demonstrates protocol/API design, stateful backend architecture, concurrency control, graph-backed storage, observability, dashboard work, and long-running maintenance. For a fast evaluation-oriented summary, see [PORTFOLIO.md](PORTFOLIO.md).

Started at a hackathon, deployed to production within weeks, and running continuously since November 2025. The repo ships a governance server with MCP and HTTP APIs, a test suite of 5,900+ passing at 77% coverage, and sustained production check-in volume, including [Lumen](https://github.com/CIRWEL/anima-mcp) on a Raspberry Pi.

---

## At a glance

| | |
|--|--|
| **Role** | Turn agent check-ins into **EISV** state (energy, integrity, entropy, void), **verdicts** (`proceed` / `guide` / `pause` / `reject`), guidance, calibration, dialectic, and a **shared knowledge graph** (PostgreSQL + Apache AGE). |
| **Default workflow** | `onboard()` → `process_agent_update()` → `get_governance_metrics()` — details in [Getting Started](docs/guides/START_HERE.md). |
| **Transports** | **Streamable HTTP** MCP on `/mcp/` (MCP 1.24+) is the primary transport. Legacy `/sse` remains deprecated compatibility. REST: `/v1/tools/call`; dashboard `/dashboard`; health `/health`. |
| **Check-in pipeline** | Identity and guards → optional onboarding/resume → **per-agent lock** (concurrent clients, one updating writer per agent) → behavioral state update → verdict and response. |
| **Tool modes** | **`GOVERNANCE_TOOL_MODE`** defaults to **`lite`**. Call **`list_tools`** on a running server for the exact mode membership; `list_tools` and `describe_tool` are always exposed. |
| **Engineering signals** | Production deployment since Nov 2025, GitHub Actions CI, ~225 source files, ~198 top-level test files, and 5,900+ passing tests. |

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
| Tests | 5,900+ passing · 188 files · 77% coverage |

[Lumen](https://github.com/CIRWEL/anima-mcp) is an embodied agent on a Raspberry Pi: sensors feed check-ins; local drawing is modulated by coherence-related dynamics. See [anima-mcp](https://github.com/CIRWEL/anima-mcp) for hardware and art pipeline details.

<p align="center">
  <img src="docs/images/dashboard.png" width="80%" alt="UNITARES web dashboard showing fleet coherence, agent status, and system health"/>
</p>

<p align="center">
  <em>Web dashboard — fleet coherence, agent status, calibration, anomaly detection.</em>
</p>

---

## What you can build on it

- **Monitoring and early warning** — Trajectories and risk signals; circuit breakers at thresholds.
- **Inter-agent observation** — Read peer state for handoff or review without scraping outputs.
- **Trajectory identity** — Behavioral signatures for continuity and fork detection.
- **Outcome correlation** — `outcome_event` feeds calibration (tests, exit codes, lint). Predictive value is still an open question; instrumentation is live.
- **Dialectic resolution** — Shared state language for structured disagreement.
- **Knowledge persistence** — Discoveries in a versioned graph with staleness awareness.
- **Session bridging** — `bind_session` links MCP and REST identities.

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

```
src/                   Server, tool schemas, behavioral state, knowledge graph, dialectic
  mcp_handlers/        Handlers: identity, lifecycle, knowledge, dialectic, observability, admin, CIRS, …
dashboard/             Web dashboard (vanilla JS + Chart.js)
tests/                 188 files, 5,900+ passing
```

| Storage | Purpose | Required |
|---------|---------|----------|
| PostgreSQL + AGE + pgvector | State, graph, dialectic, calibration | Yes |
| Redis | Session cache | No (graceful without) |

---

## Open questions

- **Outcome correlation** — `outcome_event` is wired; whether instability predicts real failures is still empirical.
- **Agent differentiation** — Behavioral EISV is the primary verdict path so trajectories do not collapse to a single ODE attractor. Baselines need ~30 updates.
- **Identity fragmentation** — Session-scoped IDs multiply across tools and CI; consolidation and trajectory re-identification are open.
- **Domain tuning** — Defaults are general-purpose; code vs. support vs. trading may need different profiles.
- **Horizontal scaling** — Single-node operation is the practical default today.

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [Getting Started](docs/guides/START_HERE.md) | Setup, workflows, tool modes |
| [Architecture](docs/UNIFIED_ARCHITECTURE.md) | Pipeline, verdicts, recovery, storage |
| [Troubleshooting](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [Dashboard](dashboard/README.md) | Web UI |
| [Database](docs/database_architecture.md) | PostgreSQL + AGE |
| [Changelog](CHANGELOG.md) | Releases |

### Canonical sources (keep README in sync)

| Topic | Source of truth |
|-------|-----------------|
| Governance pipeline, verdict meanings | [`docs/UNIFIED_ARCHITECTURE.md`](docs/UNIFIED_ARCHITECTURE.md) |
| Tool mode membership (`minimal` / `lite` / `full`) | [`src/tool_modes.py`](src/tool_modes.py) for mode sets; [`src/tool_schemas.py`](src/tool_schemas.py) for the full tool-definition registry |
| Mirror and other response shaping | [`src/mcp_handlers/response_formatter.py`](src/mcp_handlers/response_formatter.py) |
| MCP transport wiring | [`src/mcp_server.py`](src/mcp_server.py) |

When in doubt, prefer those files over this README for counts and payload shapes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and style.

## Related projects

- [**Lumen / anima-mcp**](https://github.com/CIRWEL/anima-mcp) — Embodied agent on Raspberry Pi
- [**unitares-pi-plugin**](https://github.com/CIRWEL/unitares-pi-plugin) — Pi/Lumen orchestration
- [**unitares-discord-bridge**](https://github.com/CIRWEL/unitares-discord-bridge) — Discord presence and governance events

---

## Licensing

The MCP server, dashboard, and tooling in this repo are **MIT** — see [LICENSE](LICENSE). The ODE and related dynamics ship as the proprietary compiled **`unitares-core`** dependency (installed via requirements; source not in this repo). See [CONTRIBUTING.md](CONTRIBUTING.md#compiled-dependency).

---

Built by [@CIRWEL](https://github.com/CIRWEL) | **v2.11.0**
