# Process Management Fixes

**Date:** November 18, 2025  
**Version:** 1.0.2  
**Issue:** Zombie MCP server processes accumulating over time, serving stale code

## Problem Summary

The MCP server architecture spawns a new Python process for each client connection (Cursor, Claude Desktop, etc.). When clients disconnect, these processes weren't being cleaned up, leading to:

1. **Zombie processes** from hours/days ago still running
2. **Stale code** being served (old versions without bug fixes)
3. **Resource waste** (multiple processes consuming memory)
4. **Debugging confusion** (which process is serving which client?)

## Solutions Implemented

### 1. Automatic Stale Process Cleanup on Startup ✅

**Location:** `src/mcp_server_std.py` - `cleanup_stale_processes()`

- On server startup, automatically detects and kills stale processes
- Keeps the 9 most recent processes (configurable via `MAX_KEEP_PROCESSES`)
- Logs cleanup actions to stderr for debugging
- Uses `psutil` for reliable process detection

**How it works:**
- Scans all `mcp_server_std.py` processes
- Sorts by creation time (oldest first)
- Terminates all except the 9 newest (or `MAX_KEEP_PROCESSES` if configured)
- Graceful termination (SIGTERM) with fallback to SIGKILL

### 2. Graceful Shutdown Handling ✅

**Location:** `src/mcp_server_std.py` - Signal handlers and atexit hooks

- Registers signal handlers for `SIGINT` and `SIGTERM`
- Cleans up PID file on shutdown
- Uses `atexit` hook as backup cleanup mechanism

**Benefits:**
- Proper cleanup when clients disconnect
- PID file removed on exit
- No orphaned files

### 3. PID File Management ✅

**Location:** `src/mcp_server_std.py` - `write_pid_file()`, `remove_pid_file()`

- Creates `data/.mcp_server.pid` on startup
- Stores: PID, version, start timestamp
- Removed on shutdown
- Used by cleanup script for version checking

**File format:**
```
<PID>
<version>
<start_timestamp>
```

### 4. Server Info Tool ✅

**Tool:** `get_server_info`

**Returns:**
- Server version and build date
- Current process PID and uptime
- List of all MCP server processes with details
- Health status (healthy/degraded)
- PID file status

**Usage:**
```python
# Via MCP tool call
get_server_info()
```

**Example response:**
```json
{
  "success": true,
  "server_version": "1.0.2",
  "build_date": "2025-11-18",
  "current_pid": 12345,
  "current_uptime_seconds": 3600,
  "current_uptime_formatted": "1h 0m",
  "total_server_processes": 2,
  "server_processes": [
    {
      "pid": 12345,
      "is_current": true,
      "uptime_seconds": 3600,
      "uptime_formatted": "1h 0m",
      "status": "running"
    }
  ],
  "health": "healthy"
}
```

### 5. Enhanced Cleanup Script ✅

**Location:** `scripts/cleanup_zombie_mcp_servers.sh`

**Improvements:**
- Shows process runtime for each PID
- Reads and displays version from PID file
- Better error handling and reporting
- Helpful tips at the end

**Usage:**
```bash
./scripts/cleanup_zombie_mcp_servers.sh
```

## Version Tracking

**Current Version:** `1.0.2`

Version increments:
- `1.0.1` - NaN protection fixes
- `1.0.2` - Process management and cleanup fixes

The server logs its version on startup:
```
[UNITARES MCP v1.0.2] Server starting (PID: 12345, Build: 2025-11-18)
```

## Dependencies

**New dependency:** `psutil>=5.9.0`

Added to `requirements-mcp.txt`. Install with:
```bash
pip install -r requirements-mcp.txt
```

## How It Works

### Startup Sequence

1. **Import dependencies** (including `psutil`)
2. **Clean up stale processes** (kill old ones, keep 2 newest)
3. **Write PID file** (track this process)
4. **Register signal handlers** (for graceful shutdown)
5. **Start MCP server** (ready to serve)

### Shutdown Sequence

1. **Receive signal** (SIGINT/SIGTERM from client disconnect)
2. **Signal handler fires** (logs shutdown message)
3. **Remove PID file** (clean up tracking)
4. **Exit gracefully** (process terminates)

### Automatic Cleanup

When a new server starts:
- Scans for all `mcp_server_std.py` processes
- Identifies stale ones (older than the 2 newest)
- Terminates stale processes gracefully
- Logs actions for debugging

## Testing

### Test Automatic Cleanup

1. Start multiple MCP clients (Cursor + Claude Desktop)
2. Disconnect one client
3. Start a new client
4. Check logs - should see cleanup messages

### Test Server Info Tool

```python
# Via MCP client
result = mcp_client.call_tool("get_server_info", {})
print(result)
```

### Test Manual Cleanup

```bash
# Run cleanup script
./scripts/cleanup_zombie_mcp_servers.sh

# Should show:
# - All processes found
# - Which ones are being kept
# - Which ones are being killed
# - Remaining processes
```

## Troubleshooting

### Issue: Processes still accumulating

**Check:**
1. Is `psutil` installed? `pip install psutil`
2. Are signal handlers working? Check server logs
3. Are processes being killed? Check with `ps aux | grep mcp_server_std.py`

### Issue: Can't kill processes

**Possible causes:**
- Permission denied (process owned by different user)
- Process already dead (race condition)
- Process in uninterruptible sleep (kernel issue)

**Solution:** Run cleanup script with appropriate permissions

### Issue: Version mismatch

**Check:**
1. Call `get_server_info` tool
2. Compare version with expected version
3. Restart MCP clients to spawn fresh processes

## Future Improvements

Potential enhancements:

1. **Shared state backend** (Redis/SQLite) - Single source of truth
2. **Health check endpoint** - Periodic validation
3. **Process watchdog** - Background daemon to monitor processes
4. **Version enforcement** - Reject connections from old versions
5. **Metrics collection** - Track process lifecycle events

## Related Files

- `src/mcp_server_std.py` - Main server with process management
- `scripts/cleanup_zombie_mcp_servers.sh` - Manual cleanup script
- `requirements-mcp.txt` - Dependencies (includes psutil)
- `data/.mcp_server.pid` - PID file (created at runtime)

## Notes

- The cleanup is **conservative** - keeps 9 processes by default (configurable via `MAX_KEEP_PROCESSES`)
- Processes are killed **gracefully** (SIGTERM) with fallback to SIGKILL
- PID file is in `data/` directory (gitignored)
- All cleanup actions are logged to stderr for debugging
- Health status considers 9 or fewer processes as "healthy"
- Threshold is easily adjustable in `src/mcp_server_std.py` if you need more wiggle room

---

**Status:** ✅ Implemented and ready for testing

