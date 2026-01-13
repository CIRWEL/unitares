# Claude Desktop Freeze Mitigation

## Problem

Claude Desktop can freeze during mid-task when Governance MCP performs blocking operations. This happens when synchronous file I/O or CPU-intensive operations block the event loop.

## Root Causes

1. **Blocking File I/O** - Synchronous `open()`, `json.load()`, `json.dump()` operations
2. **Blocking Lock Acquisition** - Synchronous file locking operations
3. **CPU-Intensive Operations** - Heavy computations without executor wrapping

## Solutions Implemented

### 1. Async File I/O

All file operations are now wrapped in `loop.run_in_executor()` to avoid blocking the event loop:

```python
# Before (BLOCKING - causes freeze):
with open(file_path, 'w') as f:
    json.dump(data, f)

# After (NON-BLOCKING):
loop = asyncio.get_running_loop()
await loop.run_in_executor(None, lambda: json.dump(data, open(file_path, 'w')))
```

### 2. Async Helper Functions

Helper functions that do file I/O are now async:

- `save_session()` - Dialectic session persistence
- `load_session()` - Dialectic session loading
- `_has_recently_reviewed()` - Recent review checking
- `is_agent_in_active_session()` - Active session checking
- `select_reviewer()` - Reviewer selection

### 3. Timeout Protection

All tools have automatic timeout protection via `@mcp_tool` decorator:

```python
@mcp_tool("process_agent_update", timeout=60.0)
async def handle_process_agent_update(...):
    # Automatically times out after 60s
```

### 4. Executor Wrapping

Heavy operations are wrapped in executors:

- File I/O operations
- JSON serialization/deserialization
- Lock acquisition (with async retry loops)
- State file operations

## Files Modified

1. **`src/mcp_handlers/dialectic.py`**
   - `save_session()` - Now uses executor for file writes
   - `load_session()` - Now uses executor for file reads
   - `_has_recently_reviewed()` - Made async, uses executor
   - `is_agent_in_active_session()` - Made async, uses executor
   - `select_reviewer()` - Made async to await helper functions

2. **`src/mcp_handlers/export.py`**
   - `handle_export_to_file()` - Already uses executor (verified)

3. **`src/mcp_server_std.py`**
   - `save_monitor_state_async()` - Already uses async locks and executor
   - `process_update_authenticated_async()` - Already wraps blocking operations

## Testing

To verify fixes:

1. **Monitor for freezes** - Use Claude Desktop and watch for UI freezing
2. **Check logs** - Look for timeout warnings or blocking operation logs
3. **Test heavy operations** - Run `process_agent_update` with complex state
4. **Test dialectic recovery** - Trigger circuit breaker and test recovery tools

## Client-Specific Tool Exclusion

Claude Desktop is more sensitive to hangs than Cursor. We automatically detect Claude Desktop and exclude problematic tools:

**How it works:**
- Detects Claude Desktop via parent process name
- Filters out tools in `CLAUDE_DESKTOP_EXCLUDED_TOOLS` set
- Logs which tools are excluded

**To exclude a tool for Claude Desktop:**

Edit `src/tool_modes.py`:

```python
CLAUDE_DESKTOP_EXCLUDED_TOOLS: Set[str] = {
    "problematic_tool_name",  # Add tools that cause hangs
    "web_search",              # Example: if web search causes hangs
}
```

**Note:** Web search isn't part of this MCP server - if Claude Desktop's built-in web search is hanging, that's a Claude Desktop issue, not this server. However, you can exclude any Governance MCP tools that cause hangs.

## Prevention Guidelines

When adding new handlers:

1. **Always use async** - Make handlers `async def`
2. **Wrap file I/O** - Use `loop.run_in_executor()` for all file operations
3. **Use async locks** - Prefer `async with lock:` over blocking locks
4. **Set timeouts** - Use `@mcp_tool(timeout=X)` decorator
5. **Test in Claude Desktop** - Verify no freezing during operations
6. **Add to exclusion list** - If a tool causes hangs, add it to `CLAUDE_DESKTOP_EXCLUDED_TOOLS`

## Known Issues

- **Dialectic session loading** - May still have edge cases with large session files
- **Export operations** - Large exports (>100MB) may still cause brief pauses
- **Lock contention** - Multiple agents updating simultaneously may cause delays

## Timeout Reductions

To prevent Claude Desktop hangs, timeouts have been reduced for expensive operations:

- **Export operations**: `export_to_file` 60s → 45s, `get_system_history` 30s → 20s
- **Batch operations**: `archive_old_test_agents` 30s → 20s, `backfill_calibration` 30s → 20s
- **Analysis operations**: `compare_agents` 20s → 15s, `detect_anomalies` 20s → 15s
- **Comprehensive checks**: `get_workspace_health` 30s → 20s, `cleanup_stale_locks` 30s → 15s
- **Dialectic operations**: `request_dialectic_review` 15s (use `auto_progress=true` to streamline)

**Core operations kept at reasonable timeouts:**
- `process_agent_update`: 60s (complex governance cycles need time)
- `simulate_update`: 30s (dry-run governance)

## Future Improvements

1. **Progressive loading** - Stream large files instead of loading all at once
2. **Background persistence** - Queue file writes instead of immediate writes
3. **Lock timeout reduction** - Already reduced to 2s for faster failure
4. **Progress indicators** - Add progress callbacks for long-running operations

