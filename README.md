# UNITARES Governance Framework v2.5.4

**Thermodynamic AI governance with measurable metrics and autonomous peer review.**

UNITARES makes abstract governance concepts (ethical drift, coherence, stability) **concrete and measurable** using thermodynamic state variables. It's the first system to ground AI self-governance in empirical, observable metrics.

---

## Quick Start (3 Tools)

```
1. onboard()                    → Get your identity
2. process_agent_update()       → Log your work
3. get_governance_metrics()     → Check your state
```

**That's it.** Everything else is optional.

---

## What It Does

UNITARES monitors AI agent behavior using **EISV state dynamics**:

| Variable | Range | Meaning |
|----------|-------|---------|
| **E** (Energy) | [0,1] | Exploration/productive capacity |
| **I** (Integrity) | [0,1] | Information coherence |
| **S** (Entropy) | [0,2] | Disorder/uncertainty |
| **V** (Void) | [-2,2] | E-I imbalance accumulation |

**Governance loop:**
```
Agent logs work → EISV update → Stability check → Decision (proceed/pause) → Feedback
```

**Decisions:**
- `proceed` - Continue normally
- `caution` - Approaching threshold
- `pause` - Circuit breaker triggered, needs review

---

## Installation

**Quick setup:**
```bash
git clone https://github.com/CIRWEL/governance-mcp-v1-backup.git
cd governance-mcp-v1
pip install -r requirements-core.txt
```

**Run server:**
```bash
# MCP server (recommended)
python src/mcp_server_sse.py --port 8765

# Or single-client stdio
python src/mcp_server_std.py
```

**Endpoints:**
| Endpoint | Transport | Use Case |
|----------|-----------|----------|
| `/mcp` | Streamable HTTP | **Recommended** - resumability, modern clients |
| `/sse` | Server-Sent Events | Legacy - older MCP clients |
| `/dashboard` | HTTP | Web dashboard |
| `/health` | HTTP | Health checks |

---

## MCP Configuration

> **IMPORTANT: Trailing slash required!** URLs must end with `/mcp/` (not `/mcp`).
> Without the trailing slash, you'll get a 307 redirect that most MCP clients don't follow.

**Cursor / Claude Desktop (Streamable HTTP - recommended):**
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

**With ngrok (remote access):**
```json
{
  "mcpServers": {
    "unitares": {
      "type": "http",
      "url": "https://unitares.ngrok.io/mcp/",
      "headers": {
        "Authorization": "Basic <base64-credentials>"
      }
    }
  }
}
```

**Legacy SSE (older clients):**
```json
{
  "mcpServers": {
    "unitares": {
      "type": "sse",
      "url": "http://localhost:8767/sse"
    }
  }
}
```

---

## Key Features

### 47 MCP Tools

| Category | Tools | Purpose |
|----------|-------|---------|
| **Core** | 3 | Governance cycle, metrics, simulation |
| **Lifecycle** | 10 | Agent management, archiving |
| **Knowledge Graph** | 9 | Discovery storage, semantic search |
| **Observability** | 5 | Pattern analysis, anomaly detection |
| **Admin** | 14 | Health, calibration, telemetry |
| **Identity** | 2 | Onboarding, identity management |
| **Pi Orchestration** | 6 | Mac↔Raspberry Pi coordination |

**List all tools:** `list_tools()` or see [tools/README.md](tools/README.md)

### Stability Monitoring

- **HCK v3.0** - Update coherence tracking, PI gain modulation
- **CIRS v0.1** - Oscillation detection, resonance damping
- **Circuit breakers** - Automatic pause on high risk

### Knowledge Graph

Cross-agent learning via persistent discoveries:
```
store_knowledge_graph()   → Save insights
search_knowledge_graph()  → Semantic + tag search
```

### Three-Tier Identity

| Tier | Field | Purpose |
|------|-------|---------|
| UUID | `uuid` | Immutable identifier |
| agent_id | `agent_id` | Stable session key |
| display_name | `display_name` | Human-readable name |

---

## Project Structure

```
governance-mcp-v1/
├── src/
│   ├── governance_monitor.py   # Core EISV dynamics
│   ├── cirs.py                 # Oscillation detection
│   ├── mcp_server_sse.py       # SSE server (multi-client)
│   ├── mcp_server_std.py       # Stdio server (single-client)
│   └── mcp_handlers/           # 47 tools across handlers
├── governance_core/            # Canonical math (Phase-3)
├── docs/                       # Documentation
├── data/                       # Runtime data
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

**Ethical drift (Δη):** 4-component vector measuring calibration deviation, complexity divergence, coherence quality, and stability.

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

---

## License

Research prototype - contact for licensing.

---

**Version:** 2.5.4 | **Last Updated:** 2026-02-01
