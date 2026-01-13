# date-context MCP Disconnection Fix

## Are date-context and governance MCP connected?

**No, they are separate MCP servers.** They run independently:
- `date-context`: Provides date/time utilities
- `governance`: Provides governance monitoring tools

They are both configured in your Cursor MCP config (`~/.cursor/mcp.json`) but operate independently.

## New Disconnection Issue

If date-context keeps disconnecting after the initial error handling fix, the likely cause is **ExceptionGroup handling** (Python 3.11+).

### Root Cause

When Cursor disconnects from a stdio MCP server, Python 3.11+ raises an `ExceptionGroup` containing multiple exceptions (like `BrokenPipeError`). The previous error handling didn't catch `ExceptionGroup` properly, causing the server to crash.

### Fix Applied

Added `ExceptionGroup` handling similar to the governance server:

```python
except ExceptionGroup as eg:
    # Handle ExceptionGroup from stdio_server TaskGroup (Python 3.11+)
    # Flatten and check for normal disconnect exceptions
    # Treat BrokenPipeError, ConnectionResetError, CancelledError as normal
```

### What This Fixes

1. **Graceful disconnection handling** - Server no longer crashes when Cursor disconnects
2. **ExceptionGroup support** - Properly handles Python 3.11+ exception groups
3. **Better error logging** - Unexpected errors are still logged for debugging

## Verification

After the fix, date-context should:
- ✅ Stay connected during normal use
- ✅ Handle disconnections gracefully (no crashes)
- ✅ Reconnect automatically when Cursor restarts the connection
- ✅ Log errors to stderr (visible in Cursor's MCP logs)

## If Issues Persist

1. **Check Cursor logs** - Look for MCP server errors
2. **Check process status** - `ps aux | grep date-context`
3. **Restart Cursor** - Sometimes a full restart helps
4. **Check Python version** - Ensure Python 3.11+ for ExceptionGroup support

## Related

- See `DATE_CONTEXT_CONNECTION_ISSUES.md` for SSE transport issues
- See governance server's error handling in `src/mcp_server_std.py` (lines 3085-3126)

