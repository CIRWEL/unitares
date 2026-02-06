# UNITARES Governance Framework v2.6.0

**Stability monitoring for multi-agent AI systems.**

> *Detect stuck agents, oscillation loops, and incoherent behavior before they cascade. Thermodynamic state model gives you early warning, not just crash alerts.*

UNITARES monitors AI agent behavior using continuous state variables (EISV). When agents get stuck, loop, or drift toward instability, you'll know — and can intervene before things cascade.

---

## What It Actually Does (Honest Assessment)

**Today, UNITARES provides:**
- ✅ **Stability monitoring** — Detect agents trending toward trouble
- ✅ **Stuck-agent detection** — Find agents that stopped responding
- ✅ **Oscillation detection** — Catch decision flip-flop loops (CIRS v0.1)
- ✅ **Circuit breakers** — Automatic pause when risk thresholds crossed
- ✅ **Cross-agent observability** — Compare and monitor agent fleets
- ✅ **Knowledge graph** — Persistent cross-agent learning
- ✅ **Ethical drift tracking** — ‖Δη‖² computed from parameter changes, fed into φ objective
- ✅ **Trajectory identity** — Genesis signature stored at onboard, lineage comparison detects anomalies
- ✅ **Automatic calibration** — Ground truth from objective outcomes (test results, command success), not human oracle

**What's partial/research-grade:**
- ⚠️ **"Measurable ethics"** — We measure *instability* and *drift*, but mapping these to ethical violations remains an open research question
- ⚠️ **Outcome correlation** — Does high instability actually predict bad outcomes? Needs more real-world validation

The thermodynamic math is real. The stability monitoring works. Ethical drift is computed from observable signals. Interpreting thresholds requires domain-specific tuning.

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
| `/mcp/` | Streamable HTTP | **Recommended** — modern clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

> **Note:** URLs must end with `/mcp/` (trailing slash required). Without it, you'll get a 307 redirect most clients don't follow.

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

Cross-agent persistent learning:
```
store_knowledge_graph()   → Save discoveries, insights, questions
search_knowledge_graph()  → Semantic + tag-based retrieval
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

### Trajectory Identity (New in v2.5.5)

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
- Running multiple AI agents that need coordination
- Want early warning before agents crash or loop
- Need circuit breakers for autonomous agent systems
- Building infrastructure for agent fleets

**Not a fit (yet):**
- Need verified ethical compliance (the detection layer isn't built)
- Want human-in-the-loop approval workflows (system is autonomous)
- Single-agent deployments (overkill)

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

**v2.6.0 (Feb 2026):**
- ✅ Dead code removal — ~4,200 lines of legacy code deleted (identity v1, old DBs, unused modules)
- ✅ Slim tool surface — 49 → 29 registered tools, admin tools hidden
- ✅ PostgreSQL dialectic — Fully migrated from SQLite to PostgreSQL
- ✅ Consolidated exports/observability — Unified `export()` and `observe()` tools
- ✅ Agent circuit breaker enforcement — Paused agents now actually blocked
- ✅ Redis resilience — Circuit breaker, connection pooling, retry with backoff
- ✅ 1,798 tests, 40% coverage (up from 358 tests, 25%)
- ✅ SKILL.md — Agent onboarding guide for the slim MCP surface
- ✅ Identity v2 — Three-tier model with session→UUID binding via MCP headers

**In progress:**
- 🔄 Outcome correlation — Does instability actually predict bad outcomes?
- 🔄 Threshold tuning — Domain-specific drift thresholds need real-world calibration
- 🔄 Dashboard performance — Loading speed improvements

**Future:**
- Semantic ethical drift detection (beyond parameter changes)
- Multi-agent coordination protocols (CIRS v1.0)
- Production hardening

Contributions welcome. This is research-grade infrastructure, not production-certified.

---

## Author

Built by [@CIRWEL](https://github.com/CIRWEL). Also building [Lumen/anima-mcp](https://github.com/CIRWEL/anima-mcp).

---

## License

MIT License with Attribution — see [LICENSE](LICENSE) for details.

---

**Version:** 2.6.0 | **Last Updated:** 2026-02-05
