# Async Patterns Style Guide

## Overview

This guide documents async/await patterns used in MCP handlers to prevent blocking the event loop and ensure responsive behavior.

## Core Principle

**Never block the event loop.** All I/O operations (file reads/writes, network calls, database queries) must be non-blocking.

---

## Pattern 1: File I/O with `run_in_executor`

**When to use:** Synchronous file operations (read, write, JSON parsing)

**Pattern:**
```python
import asyncio

async def handler_function():
    loop = asyncio.get_running_loop()
    
    def _sync_file_operation():
        """Synchronous file operation - runs in executor"""
        with open(file_path, 'r') as f:
            return json.load(f)
    
    # Run in executor to avoid blocking event loop
    data = await loop.run_in_executor(None, _sync_file_operation)
    return data
```

**Examples in codebase:**
- `src/mcp_handlers/core.py` - Metadata loading
- `src/mcp_handlers/dialectic.py` - Session persistence
- `src/mcp_handlers/export.py` - File exports

**Key points:**
- Use `get_running_loop()` (not deprecated `get_event_loop()`)
- Define sync function separately for clarity
- Always await the executor call

---

## Pattern 2: Metadata Loading

**When to use:** Loading agent metadata or other frequently-accessed JSON files

**Pattern:**
```python
async def handler_function():
    loop = asyncio.get_running_loop()
    
    # Load metadata (non-blocking)
    await loop.run_in_executor(None, mcp_server.load_metadata)
    
    # Now safe to access agent_metadata dict
    meta = mcp_server.agent_metadata.get(agent_id)
```

**Examples:**
- `handle_process_agent_update` - Loads metadata before processing
- `handle_get_agent_metadata` - Loads metadata before querying

**Note:** Metadata is cached in memory, so subsequent accesses are fast (no I/O).

---

## Pattern 3: File Writing with fsync

**When to use:** Critical data that must be persisted (sessions, state)

**Pattern:**
```python
async def save_critical_data(data: dict, file_path: Path):
    loop = asyncio.get_running_loop()
    
    def _write_with_fsync():
        """Write file and ensure it's on disk"""
        json_str = json.dumps(data, indent=2)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(json_str)
            f.flush()  # Ensure buffered data written
            os.fsync(f.fileno())  # Force write to disk
        
        # Verify file exists and has content
        if not file_path.exists():
            raise FileNotFoundError(f"File not found after write: {file_path}")
        
        file_size = file_path.stat().st_size
        if file_size == 0:
            raise ValueError(f"File is empty: {file_path}")
        
        return file_size
    
    # Run in executor to avoid blocking
    file_size = await loop.run_in_executor(None, _write_with_fsync)
    return file_size
```

**Examples:**
- `dialectic.py` - Session persistence
- `export.py` - Export file writing

**Key points:**
- Use `fsync()` for critical data
- Verify file exists after write
- Check file size to ensure content written

---

## Pattern 4: Lock Acquisition

**When to use:** File locking for concurrent access protection

**Pattern:**
```python
async def handler_with_locking():
    loop = asyncio.get_running_loop()
    
    # Acquire lock (non-blocking)
    lock_fd = await loop.run_in_executor(
        None,
        mcp_server.lock_manager.acquire_agent_lock,
        agent_id,
        2.0,  # timeout
        1     # max_retries
    )
    
    try:
        # Do work with lock held
        result = await do_work()
        return result
    finally:
        # Release lock (non-blocking)
        await loop.run_in_executor(
            None,
            mcp_server.lock_manager.release_agent_lock,
            agent_id,
            lock_fd
        )
```

**Examples:**
- `core.py` - Agent state updates
- `lifecycle.py` - Agent metadata updates

**Key points:**
- Always use try/finally to ensure lock release
- Run lock operations in executor
- Use reasonable timeouts (2-5 seconds)

---

## Pattern 5: Error Handler Cleanup

**When to use:** Cleanup operations in exception handlers

**Pattern:**
```python
async def handler_function():
    try:
        result = await do_work()
        return result
    except TimeoutError:
        # Cleanup stale locks (non-blocking)
        loop = asyncio.get_running_loop()
        cleanup_result = await loop.run_in_executor(
            None,
            cleanup_stale_state_locks,
            project_root,
            60.0,  # max_age_seconds
            False  # dry_run
        )
        raise
```

**Examples:**
- `core.py` - Timeout error handler cleanup

**Key point:** Even cleanup operations should be non-blocking.

---

## Anti-Patterns (What NOT to Do)

### ❌ Blocking I/O in Handler

```python
# BAD - Blocks event loop
async def bad_handler():
    with open('data.json', 'r') as f:
        data = json.load(f)  # Blocks!
    return data
```

### ❌ Synchronous File Operations

```python
# BAD - Blocks event loop
async def bad_handler():
    import os
    files = os.listdir('data/')  # Blocks!
    return files
```

### ❌ Blocking Lock Operations

```python
# BAD - Blocks event loop
async def bad_handler():
    lock_fd = mcp_server.lock_manager.acquire_agent_lock(agent_id)  # Blocks!
    # ...
```

---

## When to Use `aiofiles`

**Current status:** `aiofiles` is available but underused.

**Recommendation:** Consider migrating file I/O to `aiofiles` for better async support:

```python
import aiofiles
import aiofiles.os

async def async_file_read(file_path: Path):
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
        return json.loads(content)

async def async_file_write(file_path: Path, data: dict):
    async with aiofiles.open(file_path, 'w') as f:
        json_str = json.dumps(data, indent=2)
        await f.write(json_str)
        await f.flush()
        # Note: aiofiles doesn't support fsync directly
        # May need to use run_in_executor for fsync if critical
```

**Migration priority:** Low (current `run_in_executor` pattern works well)

---

## Performance Considerations

1. **Metadata Caching:** Metadata is cached in memory (TTL-based). First load hits disk, subsequent loads are instant.

2. **Executor Pool:** Python's default executor uses thread pool. For CPU-bound work, consider `ProcessPoolExecutor`.

3. **Batch Operations:** For multiple file operations, consider batching:
   ```python
   # Good - Batch operations
   async def batch_load(files: list[Path]):
       loop = asyncio.get_running_loop()
       results = await asyncio.gather(*[
           loop.run_in_executor(None, load_file, f) 
           for f in files
       ])
       return results
   ```

---

## Testing Async Code

When testing async handlers:

```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_handler():
    result = await handle_some_tool({})
    assert result[0].text.startswith('{"success":true')
```

**Key point:** Use `pytest.mark.asyncio` or `asyncio.run()` for async tests.

---

## Checklist for New Handlers

- [ ] All file I/O uses `run_in_executor` or `aiofiles`
- [ ] Lock operations run in executor
- [ ] Metadata loading uses cached pattern
- [ ] Error handlers don't block
- [ ] File writes use `fsync()` for critical data
- [ ] No synchronous `os` operations
- [ ] No blocking JSON parsing

---

## Related Documentation

- `src/mcp_handlers/core.py` - Examples of async patterns
- `src/mcp_handlers/dialectic.py` - Session persistence patterns
- `src/mcp_handlers/export.py` - File export patterns

