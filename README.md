# UNITARES Governance Framework v2.5.1

**Thermodynamic AI governance with autonomous peer review.**

Production-ready system for monitoring AI agent behavior using EISV (Energy, Integrity, Entropy, Void) state dynamics, with HCK/CIRS stability monitoring and three-tier identity model.

---

## 🤖 For AI Agents

**⭐ New? Start here:** [GETTING_STARTED_SIMPLE.md](docs/guides/GETTING_STARTED_SIMPLE.md) — 3 tools, 3 steps, done.

**Quick start (3 essential tools):**
1. `onboard()` — Get your identity
2. `process_agent_update()` — Log your work  
3. `get_governance_metrics()` — Check your state

**That's it.** Everything else is optional.

**CLI users:** Use `python3 scripts/unitares_lite.py` — Simple wrapper for the 3 essentials.  
**Quick reference:** [QUICK_REFERENCE.md](docs/guides/QUICK_REFERENCE.md) — One-page cheat sheet.

---

### CLI Shorthand (Optional)

We provide a zero-boilerplate shorthand script for CLI agents:

**Usage:**
```bash
python3 scripts/mcp_agent.py <tool_name> [key=value ...]
```

**Examples:**
```bash
# Identity check (auto-saves session)
python3 scripts/mcp_agent.py onboard

# Governance update
python3 scripts/mcp_agent.py process_agent_update response_text="Refactoring auth" complexity=0.7

# Store knowledge (complex args via JSON)
python3 scripts/mcp_agent.py store_knowledge_graph --json '{"discovery_type": "insight", "summary": "Found bug"}'
```

See [docs/guides/MCP_AGENT_SHORTHAND.md](docs/guides/MCP_AGENT_SHORTHAND.md) for details.

## Quick Start

**New here?** → **[GETTING_STARTED_SIMPLE.md](docs/guides/GETTING_STARTED_SIMPLE.md)** ⭐ **Start here for the simplest path**

**Or choose your path:**
- **Simple path:** [GETTING_STARTED_SIMPLE.md](docs/guides/GETTING_STARTED_SIMPLE.md) — 3 tools, 3 steps, done
- **Lite guide:** [UNITARES_LITE.md](docs/guides/UNITARES_LITE.md) — Essential tools explained simply
- **Full guide:** [START_HERE.md](docs/guides/START_HERE.md) — Complete onboarding

**Use Cases:**
- **Solo agent:** Get governance feedback on your work (start with 3 tools)
- **Multi-agent coordination:** Coordinate agents with shared knowledge graph (explore more tools when ready)

**3 essential steps:**
1. Call `onboard()` — Get your identity
2. Call `process_agent_update()` — Log your work
3. Call `get_governance_metrics()` — Check your state

**That's it.** Everything else is optional.

---

## Installation

### Self-Hosted Deployment (Recommended)

**One-command setup:**
```bash
git clone <repo>
cd governance-mcp-v1
./install.sh
```

Access:
- Dashboard: http://localhost:8765/dashboard
- MCP Endpoint: http://localhost:8765/sse

See [Deployment Guide](docs/guides/DEPLOYMENT.md) for details.

### Local Development

```bash
# Clone and install
git clone <repo>
cd governance-mcp-v1

# Minimal (stdio MCP server)
pip install -r requirements-core.txt

# OR full (SSE/HTTP server + extras)
pip install -r requirements-full.txt
```

### Optional: Apache AGE (Graph Prototype)

If you want to prototype graph-native queries (Cypher) for the **knowledge graph**, see:
- `docs/guides/AGE_PROTOTYPE.md`

### MCP Configuration

Most agents use the **MCP protocol for direct access** (Cursor, Claude Desktop, etc.).

**Cursor (SSE; recommended)** - Add to MCP config:
```json
{
  "governance-monitor-v1": {
    "url": "http://127.0.0.1:8765/sse"
  }
}
```

**Claude Desktop (stdio → SSE proxy; shared state)**:

Generate your config (prints JSON you can paste):
```bash
./scripts/mcp config claude-desktop http://127.0.0.1:8765/sse
```

**Multi-agent (SSE):**
```bash
python src/mcp_server_sse.py --port 8765
```
Then configure: `{"url": "http://127.0.0.1:8765/sse"}`

**HTTP (non-MCP clients):**

The SSE server also exposes a simple HTTP tool API:
- `GET /v1/tools` (OpenAI-style function specs)
- `POST /v1/tools/call` (execute a tool)

Recommended headers:
- `X-Session-ID: <stable-id>` (enables identity binding persistence for HTTP callers)
- Optional auth: set `UNITARES_HTTP_API_TOKEN` and send `Authorization: Bearer <token>`

Example:

```bash
curl -s http://127.0.0.1:8765/v1/tools | jq '.count'

curl -s \
  -H 'Content-Type: application/json' \
  -H 'X-Session-ID: demo-session' \
  -d '{"name":"list_tools","arguments":{"essential_only":true}}' \
  http://127.0.0.1:8765/v1/tools/call | jq
```

**Claude Code CLI (exception): no MCP.** Use the CLI bridge script instead (see `docs/guides/CLAUDE_CODE_CLI_GUIDE.md`).

### Agent Shorthand Script (Zero Boilerplate)

**NEW:** For agents calling from shell, use `mcp_agent.py` - eliminates all boilerplate:

```bash
# Simple tool call
python3 scripts/mcp_agent.py identity

# With arguments (key=value format - no f-string escaping needed!)
python3 scripts/mcp_agent.py process_agent_update response_text="My work" complexity=0.6

# With JSON input (for complex nested structures)
python3 scripts/mcp_agent.py store_knowledge_graph --json '{"discovery_type": "insight", "summary": "Found pattern"}'

# List all tools
python3 scripts/mcp_agent.py list_tools
```

**Benefits:**
- ✅ Zero syntax errors (no f-string escaping)
- ✅ Zero boilerplate (no async/await, no imports)
- ✅ Clean JSON output (easy to parse)
- ✅ Perfect for agents calling from shell

### CLI (without MCP)

```bash
cd /path/to/governance-mcp-v1
python3 -c "from src.governance_monitor import UNITARESMonitor; m = UNITARESMonitor('your_id'); print(m.process_update({'response_text': 'work summary', 'complexity': 0.5}))"
```

---

## Core Concepts

### EISV State Variables

| Variable | Range | Meaning |
|----------|-------|---------|
| **E** | [0,1] | Energy - exploration/productive capacity |
| **I** | [0,1] | Integrity - information coherence |
| **S** | [0,1] | Entropy - disorder/uncertainty |
| **V** | (-∞,∞) | Void - E-I imbalance accumulation |

### Governance Loop

```
Agent logs work → EISV dynamics update → HCK/CIRS stability check → Decision (proceed/pause) → Feedback
```

### Stability Monitoring (v2.5.0+)

- **HCK v3.0**: Update coherence ρ(t) tracks E/I alignment; PI gains modulated when unstable
- **CIRS v0.1**: Oscillation Index (OI) detects threshold-crossing patterns; resonance damping

### Decisions

- **proceed** - Continue normally
- **soft_dampen** - Resonance detected, damping applied
- **hard_block** / **pause** - Circuit breaker triggered, needs review

### Identity Model (v2.5.1+)

Three-tier identity for clearer agent identification:

| Tier | Field | Example | Mutability |
|------|-------|---------|------------|
| **UUID** | `uuid` | `f4cd825d-7d76-...` | Immutable |
| **agent_id** | `agent_id` | `cursor_20251226` | Stable (auto-generated) |
| **display_name** | `display_name` | `Claude_v2` | User-chosen |

---

## Key Tools (47 total)

| Tool | Purpose |
|------|---------|
| `process_agent_update` | Main governance cycle |
| `get_governance_metrics` | Check current state |
| `list_agents` | See all agents |
| `store_knowledge_graph` | Save discoveries |
| `request_dialectic_review` | Peer review for paused agents |

Full list: `list_tools()` or [tools/README.md](tools/README.md)

---

## Project Structure

```
governance-mcp-v1/
├── src/
│   ├── governance_monitor.py   # Core EISV dynamics + HCK/CIRS
│   ├── cirs.py                 # Oscillation detection, resonance damping
│   ├── mcp_server_std.py       # MCP server (stdio)
│   ├── mcp_server_sse.py       # MCP server (SSE multi-client)
│   └── mcp_handlers/           # 58 tools across 13 files
├── governance_core/            # Pure dynamics implementation
├── config/                     # Configuration files
├── data/                       # Runtime data (auto-created)
├── docs/                       # Documentation
└── tests/                      # Test suite
```

---

## Documentation

| Doc | Audience |
|-----|----------|
| [START_HERE.md](docs/guides/START_HERE.md) | Everyone - entry point |
| [AI_ASSISTANT_GUIDE.md](docs/reference/AI_ASSISTANT_GUIDE.md) | AI agents |
| [ONBOARDING.md](docs/guides/ONBOARDING.md) | Humans - detailed |
| [TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md) | Problem solving |
| [MCP_SETUP.md](docs/guides/MCP_SETUP.md) | Setup guide |
| [THRESHOLDS.md](docs/guides/THRESHOLDS.md) | Configuration |

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run demo
python demo_complete_system.py
```

CI/CD runs on push via GitHub Actions (Python 3.9-3.11).

---

## Architecture Highlights

- **Local-first** - All data stored locally, no cloud dependencies
- **Multi-transport** - stdio (single client) and SSE (multi-client)
- **Autonomous governance** - Peer review via dialectic protocol
- **44+ MCP tools** - Auto-registered from `tool_schemas.py`
- **Circuit breakers** - Automatic pause on high risk/low coherence

---

## Developer Guide

**Adding/modifying tools?** → **[docs/dev/TOOL_REGISTRATION.md](docs/dev/TOOL_REGISTRATION.md)**

Key points:
- Tools auto-register from `tool_schemas.py` + `mcp_handlers/*.py`
- No manual SSE decorators needed (Dec 2025 refactor)
- Session injection list: `TOOLS_NEEDING_SESSION_INJECTION` in `mcp_server_sse.py`

---

## License

Research prototype - contact for licensing.

---

**Status: Production Ready v2.5.1**

Last Updated: 2025-12-26
