# UNITARES Governance Framework v2.6.0

**Stability monitoring for multi-agent AI systems.**

> *Detect stuck agents, oscillation loops, and incoherent behavior before they cascade. Thermodynamic state model gives you early warning, not just crash alerts.*

UNITARES monitors AI agent behavior using continuous state variables (EISV). When agents get stuck, loop, or drift toward instability, you'll know — and can intervene before things cascade.

---

## What It Actually Does (Honest Assessment)

**Today, UNITARES provides:**
- ✅ **Stability monitoring** — Continuous EISV state tracking, detect agents trending toward trouble
- ✅ **Circuit breakers** — Automatic pause when risk thresholds crossed, enforced (not cosmetic)
- ✅ **Stuck-agent detection** — Find agents that stopped responding, with auto-recovery
- ✅ **Oscillation detection** — Catch decision flip-flop loops (CIRS v0.1)
- ✅ **Dialectic peer review** — Structured thesis/antithesis/synthesis protocol for dispute resolution
- ✅ **Knowledge graph** — Persistent cross-agent learning with semantic search (AGE graph DB)
- ✅ **Cross-agent observability** — Compare agents, detect anomalies, aggregate fleet metrics
- ✅ **Ethical drift tracking** — ‖Δη‖² computed from parameter changes, fed into Φ objective
- ✅ **Trajectory identity** — Genesis signatures, lineage comparison, anomaly detection
- ✅ **Web dashboard** — Real-time agent metrics, dialectic sessions, knowledge discoveries
- ✅ **Pi/Lumen orchestration** — Coordinate with Raspberry Pi-based embodied agents

**What's research-grade:**
- ⚠️ **Outcome correlation** — Does instability actually predict bad outcomes? Working theory, needs validation
- ⚠️ **Threshold tuning** — Default thresholds work, but domain-specific calibration improves accuracy

The thermodynamic math is real. The stability monitoring works. Ethical drift is computed from observable signals.

---

## Quick Start (3 Tools)

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

**That's it.** Everything else is optional.

---

## How It Works

UNITARES models agent state using **EISV dynamics**:

| Variable | Range | What It Tracks |
|----------|-------|----------------|
| **E** (Energy) | [0,1] | Productive capacity / exploration drive |
| **I** (Integrity) | [0,1] | Information coherence / consistency |
| **S** (Entropy) | [0,1] | Disorder / uncertainty |
| **V** (Void) | [0,1] | Accumulated E-I imbalance |

**Governance loop:**
```
Agent logs work → EISV update → Stability check → Decision (proceed/pause) → Feedback
```

**Decisions:**
- `proceed` — Continue normally
- `caution` — Approaching threshold (soft warning)
- `pause` — Circuit breaker triggered, needs recovery

The key insight: these are *continuous* variables, not binary pass/fail. You can see an agent *trending* toward trouble before it crashes.

---

## Installation

**Prerequisites:** PostgreSQL 16+, Redis (optional but recommended)

```bash
git clone https://github.com/CIRWEL/governance-mcp-v1-backup.git
cd governance-mcp-v1
pip install -r requirements-core.txt

# Run MCP server (recommended)
python src/mcp_server.py --port 8767

# Or single-client stdio mode
python src/mcp_server_std.py
```

**Endpoints:**
| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | **Recommended** — modern MCP clients |
| `/v1/tools/call` | REST POST | CLI, scripts, non-MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

> **Note:** MCP URLs must end with `/mcp/` (trailing slash required). Without it, you'll get a 307 redirect most clients don't follow.

**Storage stack:**
| Component | Purpose | Required |
|-----------|---------|----------|
| PostgreSQL | Agent state, dialectic sessions, calibration | Yes |
| AGE (graph extension) | Knowledge graph with semantic search | Yes |
| Redis | Session cache, rate limiting, distributed locks | Optional (graceful fallback) |

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

**With ngrok (remote):**
```json
{
  "mcpServers": {
    "unitares": {
      "type": "http",
      "url": "https://your-subdomain.ngrok.io/mcp/",
      "headers": {
        "Authorization": "Basic <base64-credentials>"
      }
    }
  }
}
```

**REST/CLI Usage (curl, scripts, GPT):**
```bash
# IMPORTANT: Include X-Session-ID header to maintain identity across calls
SESSION="my-agent-session"

# Onboard
curl -H "X-Session-ID: $SESSION" \
  -X POST http://localhost:8767/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "onboard", "arguments": {"name": "MyAgent"}}'

# Log work (same session = same identity)
curl -H "X-Session-ID: $SESSION" \
  -X POST http://localhost:8767/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "process_agent_update", "arguments": {"response_text": "Did stuff", "complexity": 0.5}}'
```

> **Without `X-Session-ID`:** Each request gets a new identity. This is intentional for security (prevents identity collision), but means you must explicitly manage sessions for REST clients.

---

## Key Features

### 29 Registered MCP Tools (Slim Surface)

v2.6.0 reduced the public tool surface from 49 to 29 registered tools. Admin/internal tools are still callable but hidden from tool listings to reduce cognitive load.

| Category | Tools | Purpose |
|----------|-------|---------|
| **Core** | `process_agent_update`, `get_governance_metrics` | Governance cycle |
| **Identity** | `onboard`, `identity` | Agent identity management |
| **Knowledge** | `knowledge`, `search_knowledge_graph`, `leave_note` | Persistent cross-agent learning |
| **Dialectic** | `request_dialectic_review`, `submit_thesis/antithesis/synthesis` | Peer review protocol |
| **Consolidated** | `agent`, `config`, `calibration`, `export`, `observe` | Unified operations |
| **Recovery** | `self_recovery`, `operator_resume_agent` | Stuck agent recovery |
| **CIRS** | `cirs_protocol` | Multi-agent coordination |
| **Pi** | `pi` | Mac ↔ Raspberry Pi orchestration |
| **Admin** | `health_check`, `get_workspace_health`, `get_connection_status` | System health |

**Discover tools:** `list_tools()` or read [SKILL.md](skills/unitares-governance/SKILL.md)

### Stability Monitoring

- **HCK v3.0** — Update coherence tracking (ρ), PI gain modulation
- **CIRS v0.1** — Oscillation Index (OI), flip detection, resonance damping
- **Circuit breakers** — Automatic pause on high risk, void activation
- **Regime detection** — DIVERGENCE → TRANSITION → CONVERGENCE → STABLE

### Knowledge Graph

Cross-agent persistent learning backed by Apache AGE (graph database):
```
knowledge(action='store', ...)       → Save discoveries, insights, questions
knowledge(action='search', ...)      → Semantic + tag-based retrieval
search_knowledge_graph(query=...)    → Direct semantic search
leave_note(message=...)              → Quick note (minimal friction)
```

### Three-Tier Identity

| Tier | Field | Example | Purpose |
|------|-------|---------|---------|
| UUID | `uuid` | `a1b2c3d4-...` | Immutable, server-assigned |
| agent_id | `agent_id` | `Claude_Opus_4_5_20260204` | Model-based, auto-generated |
| display_name | `name` | `MyAgent` | Human-readable, agent-chosen |

**How agent_id works:**
- If model type is provided: `{Model}_{Version}_{Date}` (e.g., `Claude_Opus_4_5_20260204`)
- Fallback to client hint: `{client}_{Date}` (e.g., `cursor_20260204`)
- Final fallback: `mcp_{Date}`

### Trajectory Identity

Lineage tracking for identity verification:
- **Genesis signature (Σ₀)** — Stored at first onboard, never overwritten
- **Current signature** — Updated each check-in, compared to genesis
- **Anomaly detection** — Alerts when similarity < 0.6 (possible identity drift)

```
verify_trajectory_identity()  → Two-tier check (genesis + current)
get_trajectory_status()       → View lineage health
```

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
└── tests/                      # 1,798 tests, 40% coverage
```

---

## Mathematical Foundation

UNITARES Phase-3 dynamics (see [governance_core/README.md](governance_core/README.md)):

```
dE/dt = α(I - E) - βE·S + γE·‖Δη‖²
dI/dt = -k·S + βI·C(V,Θ) - γI·I·(1-I)
dS/dt = -μ·S + λ₁(Θ)·‖Δη‖² - λ₂(Θ)·C(V,Θ) + β_complexity·C
dV/dt = κ(E - I) - δ·V
```

**Coherence function:** `C(V,Θ) = Cmax · 0.5 · (1 + tanh(Θ.C₁ · V))`

**Objective function:** `Φ = wE·E - wI·(1-I) - wS·S - wV·|V| - wEta·‖Δη‖²`

**How Δη (ethical drift) works:**
- Computed via `compute_ethical_drift()` from parameter changes: ‖Δη‖² = ‖θ_t - θ_{t-1}‖² / dim
- 4 components: calibration deviation, complexity divergence, coherence deviation, stability deviation
- Fed into φ objective with weight `wEta` (penalizes large drift)
- Also used in `update_dynamics()` to influence S (entropy) evolution

The drift is *computed*, but interpreting "high drift = bad" requires domain context. A model learning rapidly may have high drift that's actually healthy.

---

## When to Use UNITARES

**Good fit:**
- Running AI agents (one or many) that need stability monitoring
- Want early warning before agents crash, loop, or drift
- Need circuit breakers for autonomous agent systems
- Building infrastructure for coordinated agent fleets
- Embodied AI (Lumen/anima-mcp runs on a single Raspberry Pi agent)

**Not a fit (yet):**
- Need verified ethical compliance (drift detection exists, but mapping to ethical violations is research-grade)
- Need sub-second latency governance (current cycle is ~200-500ms)

---

## Documentation

| Guide | Purpose |
|-------|---------|
| [GETTING_STARTED_SIMPLE.md](docs/guides/GETTING_STARTED_SIMPLE.md) | 3-step quickstart |
| [START_HERE.md](docs/guides/START_HERE.md) | Full onboarding |
| [TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [governance_core/README.md](governance_core/README.md) | Math foundation |

---

## Testing

```bash
python -m pytest tests/ -v
```

**Current status:** 1,798 tests, 40% coverage. Core modules (governance_monitor 83%, trajectory_identity 88%, workspace_health 83%) are well-tested.

---

## Why Thermodynamic Framing?

Most monitoring approaches are:
- **Binary** — up/down, pass/fail — no early warning
- **Metrics-heavy** — CPU, memory, latency — doesn't capture agent *behavior*
- **Post-hoc** — logs, traces — useful after the fact, not preventive

UNITARES treats agent state as a continuous dynamical system. This gives you:
- **Trends, not just snapshots** — see an agent *approaching* trouble
- **Graduated responses** — caution before pause before hard stop
- **Physics-grounded intuition** — energy, entropy, coherence map to real behaviors

The thermodynamic framing isn't metaphor — it's a design choice that makes behavioral monitoring *continuous and observable*.

---

## Roadmap

**In progress:**
- 🔄 Outcome correlation — Does instability actually predict bad outcomes?
- 🔄 Threshold tuning — Domain-specific drift thresholds need real-world calibration
- 🔄 Dashboard performance — Loading speed for large agent sets
- 🔄 CIRS v1.0 — Full multi-agent coordination protocol (oscillation damping, resonance)

**Future:**
- Semantic ethical drift detection (beyond parameter changes)
- Production hardening and horizontal scaling
- WebSocket dashboard updates (replace polling)

See [CHANGELOG.md](CHANGELOG.md) for release history.

Contributions welcome. This is research-grade infrastructure, not production-certified.

---

## Author

Built by [@CIRWEL](https://github.com/CIRWEL). Also building [Lumen/anima-mcp](https://github.com/CIRWEL/anima-mcp).

---

## License

MIT License with Attribution — see [LICENSE](LICENSE) for details.

---

**Version:** 2.6.0 | **Last Updated:** 2026-02-05
