# UNITARES Governance Framework v2.5.4

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

**What's aspirational (not yet implemented):**
- ⚠️ **Ethical drift detection** — The `ethical_drift` parameter exists but defaults to `[0,0,0]`. The oracle that would detect actual ethical violations isn't built.
- ⚠️ **"Measurable ethics"** — We can measure *instability*, not *ethics*. Mapping instability to ethical violations remains an open research question.

The thermodynamic math is real. The stability monitoring works. But if you need actual ethical oversight, you'll need to build the detection layer on top.

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
python src/mcp_server_sse.py --port 8767

# Or single-client stdio mode
python src/mcp_server_std.py
```

**Endpoints:**
| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp/` | Streamable HTTP | **Recommended** — modern clients, resumable |
| `/sse` | Server-Sent Events | Legacy MCP clients |
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

---

## Key Features

### 79 MCP Tools

| Category | Count | Purpose |
|----------|-------|---------|
| **Core** | 3 | Governance cycle, metrics, simulation |
| **Lifecycle** | 10 | Agent management, archiving |
| **Knowledge Graph** | 9 | Discovery storage, semantic search |
| **Observability** | 5 | Pattern analysis, anomaly detection |
| **Recovery** | 4 | Dialectic review, stuck-agent recovery |
| **Admin** | 14 | Health, calibration, telemetry |
| **Identity** | 2 | Onboarding, identity management |
| **Pi Orchestration** | 6 | Mac↔Raspberry Pi coordination |
| **CIRS/HCK** | Various | Oscillation detection, resonance damping |

**List tools:** `list_tools()` — progressive disclosure, start with essentials

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

| Tier | Field | Purpose |
|------|-------|---------|
| UUID | `uuid` | Immutable, server-assigned |
| agent_id | `agent_id` | Session-stable key |
| display_name | `name` | Human-readable, agent-chosen |

---

## Project Structure

```
governance-mcp-v1/
├── src/
│   ├── governance_monitor.py   # Core EISV dynamics (91KB)
│   ├── cirs.py                 # Oscillation detection
│   ├── mcp_server_sse.py       # HTTP/SSE server (multi-client)
│   ├── mcp_server_std.py       # Stdio server (single-client)
│   └── mcp_handlers/           # Tool implementations
├── governance_core/            # Canonical math (Phase-3)
│   ├── dynamics.py             # Differential equations
│   ├── coherence.py            # C(V,Θ) function
│   ├── ethical_drift.py        # Δη vector (partially integrated)
│   └── scoring.py              # Φ objective, verdicts
├── docs/                       # Documentation
├── data/                       # Runtime data (agents/, knowledge/)
└── tests/                      # Test suite
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

**Note on Δη (ethical drift):** The vector is defined with 4 components (calibration deviation, complexity divergence, coherence deviation, stability deviation). The infrastructure exists in `governance_core/ethical_drift.py`. However, the *oracle* that would populate these values from actual behavioral observations isn't implemented — they default to zero. This is honest: we have the math, but not the detection layer.

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
| [QUICK_REFERENCE.md](docs/guides/QUICK_REFERENCE.md) | One-page cheat sheet |
| [TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md) | Common issues |
| [governance_core/README.md](governance_core/README.md) | Math foundation |

---

## Testing

```bash
python -m pytest tests/ -v
```

Current status: 25 tests (19 pass, 6 skipped)

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

## Roadmap (What's Missing)

1. **Ethical drift oracle** — Need classifiers that detect actual behavioral violations
2. **External validation** — Currently self-reported; need ground-truth signals
3. **Outcome correlation** — Does high instability actually predict bad outcomes?

Contributions welcome. This is research-grade infrastructure, not production-certified.

---

## Author

Built by [@CIRWEL](https://github.com/CIRWEL). Also building [Lumen/anima-mcp](https://github.com/CIRWEL/anima-mcp).

---

## License

Research prototype — contact for licensing.

---

**Version:** 2.5.4 | **Last Updated:** 2026-02-04
