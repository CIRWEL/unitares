# Developer/Debugger Agent Guide

**For agents modifying, debugging, or extending the governance system.**

## Quick Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Server (mcp_server.py)                   │
│  - Streamable HTTP transport                                    │
│  - 30 registered tools + aliases (v2.6.3)                       │
├─────────────────────────────────────────────────────────────────┤
│                    Handlers (mcp_handlers/)                      │
│  - core.py: process_agent_update, get_governance_metrics        │
│  - consolidated.py: 7 action_router tools (knowledge, agent...) │
│  - middleware.py: 8-step dispatch pipeline                       │
│  - response_formatter.py: response mode filtering               │
│  - identity_v2.py: identity (4-path architecture)               │
│  - knowledge_graph.py: KG storage with agent_id attribution     │
│  - admin.py: health_check, list_tools, etc.                     │
├─────────────────────────────────────────────────────────────────┤
│                    Identity Layer (v2.6.1)                       │
│  - UUID: Internal session binding (hidden from agents)          │
│  - agent_id: Model+date format - auto-generated, in KG          │
│  - name: User-chosen via identity(name="...")                   │
├─────────────────────────────────────────────────────────────────┤
│                    Database Layer                                │
│  - PostgreSQL: identities, sessions, EISV state (primary)       │
│  - Redis: session cache, rate limiting (optional)               │
│  - AGE extension: knowledge graph with semantic search           │
└─────────────────────────────────────────────────────────────────┘
```

## Key Files

| Purpose | File |
|---------|------|
| Server entry | `src/mcp_server.py` |
| Tool dispatch | `src/mcp_handlers/__init__.py` → `middleware.py` |
| Core governance | `src/mcp_handlers/core.py` |
| Identity/session | `src/mcp_handlers/identity_v2.py` (v2.4.0+) |
| Identity utilities | `src/mcp_handlers/utils.py` - `require_registered_agent()` |
| Knowledge graph | `src/mcp_handlers/knowledge_graph.py` - `_resolve_agent_display()` |
| KG storage | `src/storage/knowledge_graph_postgres.py` |
| EISV dynamics | `src/governance_monitor.py`, `governance_core/` |
| HCK/CIRS | `src/cirs.py` (v2.5.0+) - oscillation detection, resonance damping |
| Database | `src/db/postgres_backend.py`, `src/db/dual_backend.py` |
| Metadata store | `src/metadata_db.py` |

## Common Debugging Tasks

### 1. Check System Health
```bash
./scripts/mcp status
# or
curl http://localhost:8765/health | jq
```

### 2. View Server Logs
```bash
tail -f /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server_error.log
```

### 3. Restart Server
```bash
pkill -9 -f mcp_server
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### 4. Check Database Counts
```bash
# SQLite metadata
sqlite3 /Users/cirwel/projects/governance-mcp-v1/data/governance.db \
  "SELECT COUNT(*) FROM agent_metadata;"

# Postgres (via docker)
docker exec unitares-postgres psql -U unitares -d governance \
  -c "SELECT COUNT(*) FROM governance.identities;"
```

## Known Architectural Quirks

### Dual Data Stores
- **Postgres `identities`**: Main identity store (616 agents)
- **SQLite `agent_metadata`**: Separate metadata/audit store (619 agents)
- **They can drift!** Startup reconciliation syncs Postgres → SQLite

### kwargs Unwrapping
MCP transport passes kwargs as dict, not string. Both must be handled:
```python
if isinstance(kwargs, str):
    kwargs = json.loads(kwargs)
# kwargs is now always a dict
```
See `mcp_handlers/__init__.py:dispatch_tool()` for the fix.

### Identity Model (v2.5.5)

**Simple: 2 visible layers for agents**

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer         │ Example                      │ Purpose          │
├───────────────┼──────────────────────────────┼──────────────────┤
│ UUID          │ a1b2c3d4-e5f6-...            │ Internal only    │
│ agent_id      │ Claude_Opus_4_20251227       │ Auto-generated   │
│ name          │ "Doc Writer"                 │ Your chosen name │
└─────────────────────────────────────────────────────────────────┘
```

**For agents:** Call `identity(name="...")` to set your name. That's it.

- **UUID**: Internal session binding - agents never see this
- **agent_id**: Auto-generated from model+date, stored in KG
- **name**: Your chosen name via `identity(name="...")` (label/display_name merged)

### Session Binding (v2.4.0+, fixed v2.5.0)
- Session key auto-derived from SSE connection or stdio PID
- Identity auto-creates on first tool call (no explicit registration)
- Same session = same UUID (consistent identity)
- `identity()` tool to check your UUID, `identity(name="...")` to set your name
- **v2.5.0 fix**: `onboard`/`identity` now cache in Redis so `identity_v2` finds the binding

### Knowledge Graph Attribution (v2.5.4)
- KG stores `agent_id` (model+date) instead of UUID
- `require_registered_agent()` returns `agent_id` for KG storage
- UUID kept internal via `_agent_uuid` for session binding only
- `_resolve_agent_display()` in `knowledge_graph.py` resolves agent_id to display info
- Display names included in KG query responses for human readability

### HCK/CIRS (v2.5.0+)
- **HCK v3.0**: Coherence ρ(t) via directional E/I alignment, Continuity Energy (CE), PI gain modulation
- **CIRS v0.1**: Oscillation Index (OI) via EMA of threshold crossings, flip counting, resonance damping
- `src/cirs.py` contains `OscillationDetector`, `ResonanceDamper`, `classify_response`
- Three response tiers: `proceed`, `soft_dampen`, `hard_block`

## Tool Management (IMPORTANT)

Tool count has been a recurring source of confusion. Here's the authoritative guide:

### Three Places Tools Are Defined

| Location | Purpose | Must Match? |
|----------|---------|-------------|
| `src/tool_schemas.py` | Schema definitions (what MCP clients see) | Yes |
| `src/mcp_handlers/*.py` | Handler implementations with `@mcp_tool` decorator | Yes |
| `src/mcp_handlers/__init__.py` | Handler exports (for dispatch) | Yes |

**All three must be synchronized for a tool to work.**

### Verify Tool Count

```bash
# Quick check - run this after any tool changes
PYTHONPATH=src python3 -c "
from tool_schemas import get_tool_definitions
from mcp_handlers import TOOL_HANDLERS

schemas = get_tool_definitions()
handlers = TOOL_HANDLERS

print(f'Schemas: {len(schemas)}')
print(f'Handlers: {len(handlers)}')

schema_names = set(t.name for t in schemas)
handler_names = set(handlers.keys())

missing_handlers = schema_names - handler_names
missing_schemas = handler_names - schema_names

if missing_handlers:
    print(f'ERROR - Schemas without handlers: {missing_handlers}')
if missing_schemas:
    print(f'ERROR - Handlers without schemas: {missing_schemas}')
if not missing_handlers and not missing_schemas:
    print('✓ All tools synchronized')
"
```

### Adding a New Tool (Checklist)

1. **Handler** in `src/mcp_handlers/<category>.py`:
```python
from .decorators import mcp_tool

@mcp_tool("my_new_tool", timeout=10.0)
async def handle_my_new_tool(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    # Implementation
    return success_response({"success": True})
```

2. **Export** in `src/mcp_handlers/__init__.py`:
```python
from .category import handle_my_new_tool
```

3. **Schema** in `src/tool_schemas.py`:
```python
Tool(
    name="my_new_tool",
    description="What it does...",
    inputSchema={...}
),
```

4. **Restart server** (critical - MCP clients cache tool lists):
```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

5. **Verify** with the quick check above

### Removing a Tool (Checklist)

1. Remove from `tool_schemas.py`
2. Remove from handler file (or comment out)
3. Remove export from `__init__.py`
4. **Restart server**
5. Verify with quick check

### Common Pitfalls

| Problem | Cause | Fix |
|---------|-------|-----|
| MCP client shows old tool count | Server not restarted | `launchctl unload/load` |
| "Handler not found" | Missing export in `__init__.py` | Add the export |
| Tool appears but doesn't work | Handler missing `@mcp_tool` decorator | Add decorator |
| Syntax error on server start | Bad edit left orphan brackets | Check error logs, fix syntax |
| Count mismatch schemas vs handlers | Forgot one of the three locations | Use verify script |

### Server Restart After Changes

**Always restart after tool changes:**
```bash
# Check for syntax errors first
PYTHONPATH=src python3 -c "import mcp_server; print('✓ Compiles')"

# Then restart
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
sleep 1
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
sleep 2

# Verify server is up
curl -s http://127.0.0.1:8767/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'✓ Server {d[\"version\"]} up')"
```

### Why Claude Code Shows Different Count

Claude Code shows tools from **all** connected MCP servers combined:
- `unitares-governance`: 30 tools
- `anima` (if connected): ~30 tools
- Total shown: ~109 tools

The governance server tool count is what we control.

## Anti-Proliferation Policy

**DO NOT:**
- Create new CLI scripts (use `./scripts/mcp`)
- Add interpretation layers with custom thresholds
- Duplicate functionality that exists

**DO:**
- Use existing tools and extend them
- Check `validate_file_path()` before creating files
- Document changes in knowledge graph via `leave_note()`

## Recent Fixes

| Date | Fix | Location |
|------|-----|----------|
| Feb 4 | **v2.5.5**: Ethical drift fully integrated, trajectory identity | `governance_core/`, `trajectory_identity.py` |
| Feb 4 | Model-based agent_id fix (`Claude_Opus_4_5_20260204`) | `identity_v2.py:1446-1460` |
| Feb 4 | 310+ tests, 83-88% coverage on core modules | `tests/` |
| Dec 27 | **v2.5.4**: KG stores agent_id instead of UUID | `utils.py`, `knowledge_graph.py` |
| Dec 27 | Four-tier identity (uuid/agent_id/display_name/label) | `utils.py:require_registered_agent()` |
| Dec 27 | `_resolve_agent_display()` for human-readable KG output | `knowledge_graph.py` |
| Dec 26 | Three-tier identity model (uuid/agent_id/display_name) | `identity.py`, `identity_v2.py`, `utils.py` |
| Dec 26 | HCK v3.0 + CIRS v0.1 implementation | `src/cirs.py`, `governance_monitor.py` |
| Dec 26 | Session binding Redis cache fix | `mcp_handlers/identity.py:1355,1559` |
| Dec 25 | identity_v2.py - 3-path architecture | `mcp_handlers/identity_v2.py` |
| Dec 25 | label column added to core.agents | `db/postgres_backend.py` |
| Dec 25 | Bug #2 - attention_score → risk_score | `mcp_handlers/lifecycle.py:261` |
| Dec 24 | kwargs unwrapping for MCP transport | `mcp_handlers/__init__.py` |
| Dec 24 | Startup reconciliation Postgres→SQLite | `mcp_server.py` |

## Where to Look When Things Break

| Symptom | Check |
|---------|-------|
| "No valid session ID" | Session binding failed - check `identity_v2.py` |
| Agent count mismatch | Drift between Postgres/SQLite - check health_check |
| Tool not found | `tool_schemas.py`, handler registration |
| EISV weird values | `governance_monitor.py`, thresholds config |
| Coherence always 1.0 | No updates yet (default state) |
| OI always 0 | Normal if metrics stable on one side of thresholds |
| onboard → different agent | Redis cache miss - check `identity.py` Redis caching |
| KG shows UUID instead of name | Legacy data - `_resolve_agent_display()` handles this |
| agent_id missing in KG | Check `require_registered_agent()` in `utils.py` |
| display_name not showing | Check `_agent_display` in arguments, metadata lookup |

## Useful MCP Tools for Debugging

```python
health_check()           # System health
get_server_info()        # PID, uptime, version
debug_request_context()  # Session/transport info
get_telemetry_metrics()  # Skip rates, confidence distribution
detect_anomalies()       # Fleet-wide pattern detection
```

## Contributing Knowledge

When you fix something, document it:
```python
leave_note(
    note="Fixed X by doing Y. Root cause was Z.",
    tags=["fix", "category"]
)
```

Future agents will find it via `search_knowledge_graph()`.

---

**Written by:** Opus_4.5_CLI_20251223 (Dec 24, 2025)
**Updated:** Feb 6, 2026 - v2.6.2, action_router, middleware pipeline, 30 tools
**For:** Future developer/debugger agents
