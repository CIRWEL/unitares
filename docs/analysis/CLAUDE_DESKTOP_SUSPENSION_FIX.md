# Claude Desktop Suspension Fix

**Date:** November 20, 2025  
**Issue:** MCP server causing Claude Desktop to become suspended/hang  
**Root Cause:** Blocking lock operations without timeout  
**Status:** ✅ Fixed

---

## 🚨 Problem Identified

### Symptoms
- Claude Desktop becomes unresponsive/suspended when using MCP
- MCP server appears to hang during startup
- No error messages, just silent freeze

### Root Cause

**The Issue:**
- `load_metadata()` function used **blocking lock** (`fcntl.LOCK_SH`) without timeout
- If another process had exclusive metadata lock, `load_metadata()` would block **indefinitely**
- This happened during server startup, causing Claude Desktop to hang waiting for the lock

**Code Problem:**
```python
# BEFORE (Blocking - causes hangs)
fcntl.flock(lock_fd, fcntl.LOCK_SH)  # Blocks forever if lock held!
```

---

## ✅ Solution Implemented

### Changes Made

1. **Added Timeout to `load_metadata()`**
   - Changed from blocking lock to non-blocking with timeout
   - 2-second timeout for reads (shorter than writes)
   - Falls back to reading without lock if timeout occurs

2. **Non-Blocking Lock Acquisition**
   - Uses `fcntl.LOCK_SH | fcntl.LOCK_NB` (non-blocking)
   - Retry loop with short sleep intervals (0.05s)
   - Prevents indefinite blocking

3. **Graceful Fallback**
   - If lock timeout occurs, reads without lock
   - Safe for reads (worst case is slightly stale data)
   - Prevents hangs while maintaining data integrity

### Code Changes

**Before:**
```python
def load_metadata() -> None:
    lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)  # BLOCKING - can hang forever!
        # ... read metadata ...
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

**After:**
```python
def load_metadata() -> None:
    lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
    lock_acquired = False
    start_time = time.time()
    timeout = 2.0  # 2 second timeout
    
    try:
        # Non-blocking lock with timeout
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)  # Non-blocking!
                lock_acquired = True
                break
            except IOError:
                time.sleep(0.05)  # Short retry interval
        
        if not lock_acquired:
            # Timeout - read without lock (prevents hang)
            print("Warning: Lock timeout, reading without lock")
            # Fall through to read without lock
        
        if lock_acquired:
            # Read with lock protection
            # ... read metadata ...
            return
    
    finally:
        if lock_acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    
    # Fallback: read without lock if timeout
    # ... read metadata ...
```

---

## 🧪 Testing

### Test Scenario
1. Start Claude Desktop with MCP server configured
2. Have another process hold metadata lock
3. Verify Claude Desktop doesn't hang
4. Verify metadata loads correctly (with or without lock)

### Expected Behavior
- ✅ Claude Desktop starts without hanging
- ✅ Metadata loads within 2 seconds
- ✅ If lock timeout, reads without lock (slightly stale data acceptable)
- ✅ No indefinite blocking

---

## 📊 Impact

### Before Fix
- ❌ Claude Desktop could hang indefinitely
- ❌ No timeout mechanism
- ❌ Blocking lock acquisition
- ❌ Poor user experience

### After Fix
- ✅ Maximum 2-second delay for metadata load
- ✅ Non-blocking lock acquisition
- ✅ Graceful fallback prevents hangs
- ✅ Claude Desktop remains responsive

---

## 🔍 Related Issues

### Similar Patterns to Check

1. **Process Cleanup on Startup**
   - `cleanup_stale_processes()` runs on startup
   - Uses `psutil.process_iter()` which could be slow
   - Already has try/except, but could add timeout

2. **Agent Lock Acquisition**
   - Already has 5-second timeout ✅
   - Uses non-blocking locks ✅
   - Should be fine

3. **Metadata Save Lock**
   - Already has 5-second timeout ✅
   - Uses non-blocking locks ✅
   - Should be fine

---

## 📚 Related Documentation

- **Metadata Lock Fix**: `docs/analysis/METADATA_LOCK_FIX.md`
- **Too Many Cooks Incident**: `docs/analysis/TOO_MANY_COOKS_INCIDENT.md`
- **MCP Concurrency Architecture**: `docs/analysis/MCP_CONCURRENCY_ARCHITECTURE.md`

---

## 🎯 Key Takeaways

1. **Always use timeouts for locks** - Prevents indefinite blocking
2. **Non-blocking locks with retry** - Better than blocking locks
3. **Graceful fallbacks** - Better to read stale data than hang forever
4. **Startup operations are critical** - Must not block client initialization

---

**Status:** ✅ Fixed  
**Impact:** Claude Desktop no longer hangs when starting MCP server  
**Risk:** Low - fallback ensures data is always readable

