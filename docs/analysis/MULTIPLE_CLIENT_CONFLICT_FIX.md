# Multiple Client Conflict Fix

**Date:** November 20, 2025  
**Issue:** Only one client (Cursor or Claude Desktop) can connect to MCP at a time  
**Root Cause:** Aggressive process cleanup killing active connections  
**Status:** ✅ Fixed

---

## 🚨 Problem Identified

### Symptoms
- If Cursor connects to MCP, Claude Desktop can't connect
- If Claude Desktop quits, Cursor loses MCP connection
- If Cursor reconnects, Claude Desktop loses connection
- **Mutual exclusivity** - only one client can use MCP at a time

### Root Cause

**The Issue:**
- Each client spawns its own MCP server process
- When a new process starts, it runs `cleanup_zombies()` and `cleanup_stale_processes()`
- The cleanup logic was **too aggressive** - killing processes that might be active connections from other clients
- Heartbeats are only written when `process_agent_update` is called, not on startup
- So when a new client starts, it sees other processes without recent heartbeats and kills them

**What Happened:**
```
Timeline of Conflict:

1. Cursor starts → spawns process A → writes heartbeat
2. Claude Desktop starts → spawns process B → cleanup runs
3. Process B sees process A has no "recent" heartbeat (because no update yet)
4. Process B kills process A → Cursor loses connection ❌

OR

1. Claude Desktop starts → spawns process A → writes heartbeat  
2. Cursor starts → spawns process B → cleanup runs
3. Process B kills process A → Claude Desktop loses connection ❌
```

---

## ✅ Solution Implemented

### Changes Made

1. **Write Heartbeat on Startup**
   - Write heartbeat immediately when process starts
   - Before cleanup runs, mark this process as active
   - Prevents other clients from killing this process

2. **Less Aggressive Cleanup**
   - Only kill processes that are **truly stale**:
     - Older than 5 minutes **AND**
     - No recent heartbeat (5+ minutes old)
   - Don't kill processes just because they exceed limit if they're recent

3. **Check Heartbeats Before Killing**
   - Check heartbeat files to see if process is active
   - Only kill if heartbeat is stale (5+ minutes old)
   - Preserves active connections from other clients

### Code Changes

**Before:**
```python
# Cleanup runs, kills processes without checking heartbeats properly
cleaned = process_mgr.cleanup_zombies(max_keep_processes=MAX_KEEP_PROCESSES)
cleanup_stale_processes()  # Kills oldest processes if over limit
```

**After:**
```python
# Write heartbeat FIRST to mark this process as active
process_mgr.write_heartbeat()

# Cleanup with longer timeout - only kill truly stale processes
cleaned = process_mgr.cleanup_zombies(max_age_seconds=300, max_keep_processes=MAX_KEEP_PROCESSES)

# Cleanup checks heartbeats before killing
cleanup_stale_processes()  # Only kills if >5min old AND no heartbeat
```

**Cleanup Logic:**
```python
# Only kill processes that:
# 1. Are older than 5 minutes AND don't have recent heartbeat
# 2. AND we're over the limit
stale_processes = [
    p for p in current_processes[:-MAX_KEEP_PROCESSES]
    if p['age_seconds'] > 300 and not p['has_recent_heartbeat']
]
```

---

## 🧪 Testing

### Test Scenario
1. Start Cursor with MCP configured
2. Start Claude Desktop with MCP configured
3. Verify both can connect simultaneously
4. Verify both can use MCP tools
5. Verify cleanup doesn't kill active connections

### Expected Behavior
- ✅ Both Cursor and Claude Desktop can connect simultaneously
- ✅ Each client maintains its own connection
- ✅ Cleanup only kills truly stale processes (5+ minutes old, no heartbeat)
- ✅ Active connections are preserved

---

## 📊 Impact

### Before Fix
- ❌ Only one client could connect at a time
- ❌ New client would kill existing client's process
- ❌ Aggressive cleanup killed active connections
- ❌ Poor user experience

### After Fix
- ✅ Multiple clients can connect simultaneously
- ✅ Each client maintains its own process
- ✅ Cleanup only kills truly stale processes
- ✅ Active connections are preserved

---

## 🔍 Architecture Understanding

### How MCP Servers Work

**stdio-based MCP:**
- Each client spawns **one process** per connection
- Process communicates via `stdin`/`stdout` pipes
- Multiple clients = multiple processes
- Processes share the same metadata file (with locking)

**Process Model:**
```
Cursor Window
  └── Process PID 12345 (heartbeat_12345.txt)
  
Claude Desktop
  └── Process PID 12346 (heartbeat_12346.txt)
  
Both processes:
  - Share metadata file (with locks)
  - Each has its own heartbeat file
  - Can coexist peacefully ✅
```

---

## 📚 Related Documentation

- **MCP Concurrency Architecture**: `docs/analysis/MCP_CONCURRENCY_ARCHITECTURE.md`
- **Process Management**: `src/process_cleanup.py`
- **Metadata Lock Fix**: `docs/analysis/METADATA_LOCK_FIX.md`

---

## 🎯 Key Takeaways

1. **Write heartbeats on startup** - Mark process as active before cleanup
2. **Check heartbeats before killing** - Don't kill active connections
3. **Use longer timeouts** - 5 minutes is reasonable for "stale"
4. **Preserve active connections** - Multiple clients should coexist

---

**Status:** ✅ Fixed  
**Impact:** Multiple clients can now connect simultaneously without conflicts  
**Risk:** Low - cleanup is now more conservative and preserves active connections

