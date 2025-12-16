# UNITARES Governance Framework v2.3.0

**Thermodynamic AI governance with autonomous peer review.**

Production-ready system for monitoring AI agent behavior using EISV (Energy, Integrity, Entropy, Void) state dynamics.

---

## Quick Start

**New here?** → **[START_HERE.md](START_HERE.md)**

**3 steps:**
1. Get API key via MCP or CLI bridge
2. Log your work
3. Receive governance feedback

---

## Installation

```bash
# Clone and install
git clone <repo>
cd governance-mcp-v1

# Minimal (stdio MCP server)
pip install -r requirements-core.txt

# OR full (SSE/HTTP server + extras)
# pip install -r requirements-full.txt
```

### Optional: Apache AGE (Graph Prototype)

If you want to prototype graph-native queries (Cypher) for the **knowledge graph**, see:
- `docs/guides/AGE_PROTOTYPE.md`

### MCP Configuration

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
Agent logs work → EISV dynamics update → Decision (proceed/pause) → Feedback
```

### Decisions

- **proceed** - Continue normally
- **pause** - Circuit breaker triggered, needs review

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
│   ├── governance_monitor.py   # Core EISV dynamics
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
| [START_HERE.md](START_HERE.md) | Everyone - entry point |
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
- **47 MCP tools** - Organized in handler registry pattern
- **Circuit breakers** - Automatic pause on high risk/low coherence

---

## License

Research prototype - contact for licensing.

---

**Status: Production Ready v2.3.0**

Last Updated: 2025-12-09
