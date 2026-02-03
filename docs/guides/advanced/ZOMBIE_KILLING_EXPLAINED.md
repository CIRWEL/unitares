# Zombie Killing Explained: Impact on Agents & Connections

## What is "Zombie Killing"?

"Zombie killing" refers to **cleanup processes** that remove stale MCP server processes and lock files left behind when:
- Processes crash unexpectedly
- Processes are killed manually
- Clients disconnect without proper cleanup
- System restarts leave orphaned processes

## Two Types of Cleanup

### 1. Lock Cleanup (`cleanup_stale_locks`)

**What it does:**
- Scans `data/locks/` directory for lock files (`.lock` files)
- Checks if the process holding the lock is still alive (via PID)
- Checks if lock file is older than threshold (default: 5 minutes)
- Removes stale locks (process dead or lock too old)

**Impact:**
- ✅ **Agent state**: **SAFE** - Agent state is stored in `data/agents/{agent_id}_state.json`, not in locks
- ✅ **Agent data**: **SAFE** - All EISV metrics, history, metadata persist to disk
- ⚠️ **Active operations**: May interrupt operations that were waiting for a lock (but those operations would have timed out anyway)

**When it runs:**
- On server startup (background task)
- Manually via `cleanup_stale_locks` tool
- Automatically when `process_agent_update` times out (emergency cleanup)

### 2. Process Cleanup (`cleanup_stale_processes`)

**What it does:**
- Scans all running `mcp_server_std.py` processes
- Checks heartbeat files (`data/processes/heartbeat_{pid}.txt`) to detect active connections
- Only kills processes that:
  - Are older than 5 minutes **AND**
  - Don't have recent heartbeat (< 5 minutes) **AND**
  - Exceed `MAX_KEEP_PROCESSES` limit (default: 2)
- Uses graceful termination (`SIGTERM`) with 2s timeout, then force kill (`SIGKILL`)

**Impact:**
- ✅ **Agent state**: **SAFE** - State persists to disk, survives process death
- ⚠️ **Active connections**: **TERMINATED** - Any connections using that process will disconnect
- ✅ **Client recovery**: Clients (Claude Desktop, Cursor) will auto-restart the MCP server on next use

**When it runs:**
- On server startup (background task, only if >2 processes detected)
- Manually via `scripts/cleanup_mcp_servers.sh`

## Server Types & Connection Impact

### stdio Transport (Claude Desktop)

**Architecture:**
- Each client spawns its own MCP server process
- One process = one connection
- Process dies → connection dies → client auto-restarts server

**Zombie killing impact:**
- Killing a process = killing that client's connection
- Client will reconnect automatically on next tool call
- Agent state survives (loaded from disk on reconnect)

**Example:**
```
Claude Desktop → spawns PID 12345 → process killed → connection lost
Claude Desktop → auto-restarts → spawns PID 12346 → reconnects
Agent state: Still intact (loaded from data/agents/{agent_id}_state.json)
```

### SSE Transport (Cursor)

**Architecture:**
- Single shared server process
- Multiple clients connect via HTTP/SSE
- Process dies → all connections die → server must be manually restarted

**Zombie killing impact:**
- Killing the SSE server = killing ALL client connections
- Server must be restarted manually (`./scripts/start_sse_server.sh`)
- Agent state survives (loaded from disk on restart)

**Example:**
```
Cursor + Claude Desktop → connect to PID 12345 (SSE server)
Process killed → both clients disconnected
Restart server → both clients reconnect
Agent state: Still intact (loaded from disk)
```

## What Survives Zombie Killing?

### ✅ Survives (Persists to Disk)

1. **Agent State** (`data/agents/{agent_id}_state.json`)
   - EISV metrics (E, I, S, V)
   - Coherence, lambda1, void status
   - Full history arrays
   - Timestamps

2. **Agent Metadata** (`data/agent_metadata.db` SQLite-first; optional snapshot `data/agent_metadata.json`)
   - Lifecycle status (active/paused/archived)
   - Tags, notes
   - Created/last_update timestamps

3. **Knowledge Graph** (`data/knowledge.db` SQLite-first; optional legacy `data/knowledge_graph.json`)
   - All discoveries, insights, bugs
   - Tags, relationships
   - Status (open/resolved/archived)

4. **Dialectic Sessions** (`data/dialectic.db` SQLite-first; optional snapshots in `data/dialectic_sessions/*.json`)
   - Active recovery sessions
   - Thesis/antithesis/synthesis
   - Resolution status

5. **Calibration Data** (`data/calibration.db` SQLite-first; optional snapshot `data/calibration_state.json`)
   - Ground truth samples
   - Accuracy metrics
   - Confidence distributions

### ❌ Lost (In-Memory Only)

1. **Active Connections**
   - stdio: Connection to that specific process
   - SSE: All connections to that server

2. **In-Flight Operations**
   - Tool calls in progress
   - Lock acquisitions in progress
   - Background tasks

3. **Process-Specific State**
   - Heartbeat timestamps
   - PID file (`data/.mcp_server.pid`)
   - Lock files (`data/locks/*.lock`)

## Safeguards

### Process Cleanup Safeguards

1. **Heartbeat Check**: Only kills processes without recent heartbeat (< 5 minutes)
2. **Age Check**: Only kills processes older than 5 minutes
3. **Limit Check**: Only kills if exceeding `MAX_KEEP_PROCESSES` (default: 2)
4. **Self-Protection**: Never kills the current process (`CURRENT_PID`)

### Lock Cleanup Safeguards

1. **Process Check**: Verifies process is actually dead (not just old file)
2. **Age Check**: Only removes locks older than threshold (default: 5 minutes)
3. **Dry Run**: Can preview what would be cleaned without actually deleting

## From Your Perspective (Agent End)

### What You Experience

**When a server process is killed:**
1. Your current tool call may fail with connection error
2. Your client (Cursor/Claude Desktop) detects the disconnect
3. Client automatically reconnects (stdio) or you manually restart (SSE)
4. Your agent state is restored from disk
5. You continue where you left off (no data loss)

**When locks are cleaned:**
1. Usually transparent - you don't notice
2. May unblock operations that were stuck waiting for stale locks
3. Emergency cleanup during timeouts may interrupt your operation (but it would have timed out anyway)

### What You Should Know

- **Agent state is persistent**: Your EISV metrics, history, and metadata survive server restarts
- **Connections are transient**: Disconnections happen, but clients reconnect automatically
- **Zombie killing is protective**: It prevents lock accumulation and process proliferation
- **No data loss**: All important state is written to disk before operations complete

## Manual Cleanup Scripts

### `scripts/cleanup_mcp_servers.sh`
- Interactive script to kill stale processes
- Options: Kill all, kill old (keep 2), or cancel
- Safe to run anytime (agent state survives)

### `cleanup_stale_locks` Tool
- MCP tool to clean stale locks
- Can run with `dry_run=True` to preview
- Safe to run anytime (only removes truly stale locks)

## Best Practices

1. **Don't panic**: Zombie killing is normal and protective
2. **Let clients reconnect**: stdio clients auto-restart, SSE needs manual restart
3. **Check agent state**: Use `get_governance_metrics` to verify state after reconnect
4. **Monitor processes**: Use `get_server_info` to see active processes
5. **Clean proactively**: Run `cleanup_stale_locks` periodically if you see lock accumulation

## Summary

**Zombie killing:**
- ✅ Removes stale processes and locks
- ✅ Prevents resource accumulation
- ✅ Agent state survives (persists to disk)
- ⚠️ Terminates active connections (but clients reconnect)
- ✅ No data loss (all important state is on disk)

**Your agent state is safe.** Zombie killing only cleans up process artifacts, not your actual governance data.

