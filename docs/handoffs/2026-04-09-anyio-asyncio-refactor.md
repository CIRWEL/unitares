# Handoff: anyio-asyncio Runtime Conflict in Governance MCP Server

**Date:** 2026-04-09
**From:** Claude Code session (commit d038771)
**Priority:** High — health_check via MCP is broken, REST /v1/tools/call hangs for DB-touching tools

## The Problem

The governance MCP server has two async runtimes that don't coexist:

1. **anyio** — used by the MCP SDK's StreamableHTTPSessionManager. Started via `start_streamable_http()` in `mcp_server.py` which creates a persistent `anyio.create_task_group()`.

2. **asyncio** — used by asyncpg (PostgreSQL), aioredis (Redis), and all server business logic.

When any MCP tool handler `await`s an asyncpg or Redis operation, the coroutine deadlocks. The anyio task group's event loop scheduling starves the asyncio coroutines.

## What Works

- MCP tool calls that read in-memory state (`get_governance_metrics`, `process_agent_update` for cached agents)
- `call_pi_tool` — rewritten to use sync `httpx.Client` in `run_in_executor` (bypasses anyio entirely)
- REST endpoints that don't touch DB (`GET /health`, `GET /v1/tools`, `GET /dashboard`)
- All 5908 tests pass

## What's Broken

- `health_check` via MCP — times out at 20s because `db.health_check()`, `calibration_health_check_async()`, etc. deadlock
- REST `POST /v1/tools/call` — hangs for any tool whose handler awaits DB operations
- KG health check — `get_knowledge_graph()` deadlocks on AGE backend init (disabled as workaround)
- KG lifecycle startup cleanup — disabled (`startup_kg_lifecycle` in background_tasks.py)

## What I Tried

### 1. Starlette lifespan with `session_manager.run()` (FAILED)
```python
@contextlib.asynccontextmanager
async def _lifespan(app):
    async with _streamable_session_manager.run():
        yield

app = Starlette(routes=[], lifespan=_lifespan)
```
**Result:** Server froze completely — no endpoints responded. The lifespan forces ALL request handling through anyio, making the conflict universal instead of partial.

### 2. `json_response=True` on StreamableHTTPSessionManager (FAILED)
**Result:** Claude Code's MCP client didn't receive responses. Reverted.

### 3. `Starlette(routes=[])` instead of `mcp.sse_app()` (PARTIAL)
**Result:** SSE removed successfully, but didn't fix the deadlock. REST POST to `/v1/tools/call` also hung with the bare Starlette app. Reverted to `sse_app()` as base — the SSE transport is unused but the app scaffold works.

### 4. Wrapping DB calls in `asyncio.wait_for(timeout=5)` (FAILED)
**Result:** `asyncio.wait_for` cannot cancel coroutines blocked inside anyio-managed resources. The timeout fires but cancellation doesn't propagate. KG health_check showed 116s elapsed with a 5s timeout.

## Key Files

- `src/mcp_server.py:795-812` — `start_streamable_http()` creates the problematic anyio task group
- `src/services/runtime_queries.py:360+` — `get_health_check_data()` with all the async DB calls
- `src/mcp_handlers/observability/pi_orchestration.py:174+` — `call_pi_tool` (fixed — uses sync httpx in executor)
- `src/background_tasks.py:131` — `startup_kg_lifecycle` (disabled)
- `src/storage/knowledge_graph_age.py:897` — `health_check()` does AGE graph queries

## Architecture Options (Not Vetted)

### Option A: Run DB ops in executor threads
Wrap every asyncpg/Redis `await` in `loop.run_in_executor()` using synchronous DB clients (like psycopg2 instead of asyncpg). This is what we did for `call_pi_tool` and it works.

**Pro:** Surgical fix, doesn't change the MCP transport setup.
**Con:** Replaces async DB with sync-in-thread everywhere. Loses connection pooling benefits. Large surface area.

### Option B: Replace manual anyio task group with asyncio-native equivalent
The `start_streamable_http()` function manually sets `_streamable_session_manager._task_group` and `_has_started`. If we could create a task group equivalent using pure asyncio (no anyio), the conflict disappears.

**Pro:** Fixes root cause. Minimal blast radius.
**Con:** Depends on MCP SDK internals. May break with SDK updates.

### Option C: Use anyio throughout (full migration)
Switch from asyncpg to an anyio-compatible PostgreSQL driver. Use anyio for all async operations.

**Pro:** Clean architecture. No runtime conflict.
**Con:** Massive refactor. asyncpg is deeply embedded. May not have a good anyio-native PG driver.

### Option D: Isolate the MCP transport in a subprocess
Run the StreamableHTTP transport in a separate process that proxies tool calls to the main server via IPC.

**Pro:** Complete isolation. Zero conflict.
**Con:** Adds complexity, latency, and a new failure mode.

### Option E: Investigate why the lifespan approach froze
The Starlette lifespan with `session_manager.run()` is the MCP SDK's recommended pattern. It froze the server — but I didn't diagnose WHY thoroughly. It's possible a specific background task or middleware was the actual blocker, not the lifespan itself.

**Pro:** If it works, it's the cleanest solution.
**Con:** Requires careful investigation of what specifically blocked.

## Recommendation

Start with **Option E**. The lifespan approach is the SDK's intended pattern. My attempt was during a chaotic session with many variables changing simultaneously. A clean investigation — starting from a minimal Starlette app with just the lifespan + one DB call — would isolate whether the conflict is fundamental or an interaction bug.

If Option E fails definitively, **Option B** is the next best bet.

## Reproduction

```bash
# Start the server
launchctl load ~/Library/LaunchAgents/com.unitares.governance-mcp.plist

# This works (in-memory):
# MCP get_governance_metrics via Claude Code

# This deadlocks (DB call):
curl -s --max-time 10 -X POST http://localhost:8767/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"health_check","arguments":{"lite":true}}'
# Returns 0 bytes after 10s timeout
```
