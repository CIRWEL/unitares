# PostgreSQL Connection Timeout Fix

**Created:** January 4, 2026  
**Status:** Fixed

---

## Problem

The server was getting stuck at 100% CPU when PostgreSQL wasn't running. The `asyncpg.create_pool()` call was retrying the connection indefinitely in a tight loop, causing the process to hang.

**Symptoms:**
- Process at 100% CPU
- Logs showing: "Failed to initialize database: Connect call failed"
- Server unresponsive

**Root Cause:**
`asyncpg.create_pool()` doesn't have a connection timeout parameter. When PostgreSQL isn't available, it tries to connect, the connection attempt hangs, then retries immediately in a tight loop.

---

## Solution

Added `asyncio.wait_for()` timeout wrapper around `create_pool()` calls:

1. **Fast failure:** If PostgreSQL isn't available, fail after 5 seconds instead of retrying forever
2. **Clear error:** Provide helpful error message telling user to check if PostgreSQL is running
3. **Applied to both:** Fixed both `init()` and `_ensure_pool()` methods

**Code Changes:**
- `src/db/postgres_backend.py` - Added timeout wrapper around `asyncpg.create_pool()`
- Timeout: 5 seconds (fast enough to not hang, long enough for slow networks)

---

## How It Works Now

**Before:**
```python
self._pool = await asyncpg.create_pool(...)  # Retries forever if PostgreSQL down
```

**After:**
```python
self._pool = await asyncio.wait_for(
    asyncpg.create_pool(...),
    timeout=5.0  # Fail fast if PostgreSQL isn't available
)
```

**Error Handling:**
- `asyncio.TimeoutError` → Clear error message with troubleshooting steps
- Other exceptions → Re-raised with context about PostgreSQL connection

---

## Testing

To test the fix:
1. Stop PostgreSQL: `brew services stop postgresql` (or equivalent)
2. Start server: Should fail fast with clear error message
3. Start PostgreSQL: Server should connect successfully

---

## Prevention

**For Users:**
- Check if PostgreSQL is running before starting server
- Use `DB_BACKEND=sqlite` if PostgreSQL isn't needed
- Check logs for connection errors

**For Developers:**
- Always wrap `asyncpg.create_pool()` in timeout
- Provide clear error messages
- Consider fallback to SQLite if PostgreSQL unavailable

---

**Last Updated:** January 4, 2026  
**Status:** Fixed

