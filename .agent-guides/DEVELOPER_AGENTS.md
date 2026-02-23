# Developer/Debugger Agent Guide

**For agents modifying, debugging, or extending the governance system.**

## Quick Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Server (mcp_server.py)                   │
│  - Streamable HTTP transport (port 8767)                       │
│  - 30 registered tools + aliases (v2.7.0)                       │
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
│  - PostgreSQL + AGE: ALL persistent data (Docker, port 5432)    │
│  - Redis: session cache, rate limiting (Docker, port 6379)      │
│  - NO SQLite. NO Homebrew PostgreSQL. NO dual backends.         │
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
| KG storage (AGE) | `src/storage/knowledge_graph_age.py` |
| KG storage (FTS) | `src/storage/knowledge_graph_postgres.py` |
| EISV dynamics | `src/governance_monitor.py`, `governance_core/` |
| HCK/CIRS | `src/cirs.py` (v2.5.0+) - oscillation detection, resonance damping |
| Database backend | `src/db/postgres_backend.py` |
| Agent storage | `src/agent_storage.py` |

## Common Debugging Tasks

### 1. Check System Health
```bash
curl http://localhost:8767/health | jq
```

### 2. View Server Logs
```bash
tail -f /Users/cirwel/projects/governance-mcp-v1/data/logs/mcp_server_error.log
```

### 3. Restart Server
```bash
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
```

### 4. Check Database Counts
```bash
# PostgreSQL (Docker container: postgres-age, port 5432)
docker exec postgres-age psql -U postgres -d governance \
  -c "SELECT COUNT(*) FROM core.identities;"

# Knowledge graph
docker exec postgres-age psql -U postgres -d governance \
  -c "SELECT COUNT(*) FROM core.discoveries;"
```

## Known Architectural Quirks

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
- Session key auto-derived from MCP Streamable HTTP `mcp-session-id` header or stdio PID
- Identity auto-creates on first tool call (no explicit registration)
- Same session = same UUID (consistent identity)
- `identity()` tool to check your UUID, `identity(name="...")` to set your name
- `onboard`/`identity` cache in Redis so `identity_v2` finds the binding

### Knowledge Graph Attribution (v2.5.4)
- KG stores `agent_id` (model+date) instead of UUID
- `require_registered_agent()` returns `agent_id` for KG storage
- UUID kept internal via `_agent_uuid` for session binding only
- `_resolve_agent_display()` in `knowledge_graph.py` resolves agent_id to display info
- Display names included in KG query responses for human readability

### HCK/CIRS (v2.5.0+)
- **HCK v3.0**: Coherence rho(t) via directional E/I alignment, Continuity Energy (CE), PI gain modulation
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
    print('All tools synchronized')
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
PYTHONPATH=src python3 -c "import mcp_server; print('Compiles')"

# Then restart
launchctl unload ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
sleep 1
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist
sleep 2

# Verify server is up
curl -s http://127.0.0.1:8767/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Server {d[\"version\"]} up')"
```

## Anti-Proliferation Policy

**DO NOT:**
- Create new CLI scripts (use `./scripts/mcp`)
- Add interpretation layers with custom thresholds
- Duplicate functionality that exists

**DO:**
- Use existing tools and extend them
- Check `validate_file_path()` before creating files
- Document changes in knowledge graph via `leave_note()`

## Where to Look When Things Break

| Symptom | Check |
|---------|-------|
| "No valid session ID" | Session binding failed - check `identity_v2.py` |
| Tool not found | `tool_schemas.py`, handler registration |
| EISV weird values | `governance_monitor.py`, thresholds config |
| V always 0 for all agents | V clamp was `max(0.0,...)` - fixed to `max(-1.0,...)` in v2.6.4 |
| Agent identity lost between sessions | Add `X-Agent-Name` header to MCP config |
| Metadata stale after DB changes | `load_metadata_async(force=True)` or wait 60s |
| Coherence always 1.0 | No updates yet (default state) |
| OI always 0 | Normal if metrics stable on one side of thresholds |
| onboard -> different agent | Redis cache miss - check `identity_v2.py` Redis caching |
| KG shows UUID instead of name | Legacy data - `_resolve_agent_display()` handles this |

## Useful MCP Tools for Debugging

```python
health_check()              # System health
debug_request_context()     # Session/transport info
observe(action='telemetry') # Skip rates, confidence distribution
observe(action='anomalies') # Fleet-wide pattern detection
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

**Updated:** Feb 22, 2026
**For:** Future developer/debugger agents
