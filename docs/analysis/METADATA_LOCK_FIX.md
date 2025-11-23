# Metadata File Race Condition Fix

**Date:** November 20, 2025  
**Issue:** Multiple agents couldn't use MCP simultaneously  
**Root Cause:** Metadata file race condition  
**Status:** ✅ Fixed

---

## 🎯 Problem Identified

### Symptoms
- Multiple agents couldn't use the MCP server simultaneously
- Agents would hang or timeout when trying to process updates
- Metadata file corruption or lost updates

### Root Cause

**The Issue:**
- Each agent has its own lock file (`{agent_id}.lock`) for agent-specific state
- But ALL agents write to the SAME metadata file (`agent_metadata.json`)
- Per-agent locks don't protect the shared metadata file!

**What Happened:**
```
Timeline of Race Condition:

1. Agent A acquires lock_A, reads metadata, modifies it
2. Agent B acquires lock_B, reads metadata, modifies it  
3. Agent A writes metadata (overwrites Agent B's changes) ❌
4. Agent B writes metadata (overwrites Agent A's changes) ❌
5. Result: Lost updates, metadata corruption, or file conflicts
```

---

## ✅ Solution Implemented

### Changes Made

1. **Added Global Metadata Lock**
   - Created `.metadata.lock` file for exclusive metadata access
   - Separate from per-agent locks
   - Uses `fcntl.flock()` for file-based locking

2. **Updated `save_metadata()` Function**
   - Now acquires exclusive lock before writing
   - Reloads metadata first to merge concurrent updates
   - Uses atomic write pattern (fsync) to ensure disk persistence

3. **Updated `load_metadata()` Function**
   - Now acquires shared lock when reading
   - Prevents reading while another process is writing

### Code Changes

**Before:**
```python
def save_metadata() -> None:
    """Save agent metadata to file"""
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        data = {...}
        json.dump(data, f, indent=2)
```

**After:**
```python
def save_metadata() -> None:
    """Save agent metadata to file with locking to prevent race conditions"""
    # Acquire exclusive lock
    lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Reload to merge concurrent updates
        # Write with fsync for atomicity
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

---

## 🧪 Testing

### Test Scenario
1. Start multiple agents simultaneously
2. Process updates from each agent concurrently
3. Verify metadata file integrity
4. Check for lost updates

### Expected Behavior
- ✅ Multiple agents can use MCP simultaneously
- ✅ No metadata corruption
- ✅ No lost updates
- ✅ Proper lock acquisition/release

---

## 📊 Architecture

### Lock Hierarchy

```
Global Metadata Lock (.metadata.lock)
├── Exclusive lock: For writes (save_metadata)
└── Shared lock: For reads (load_metadata)

Per-Agent Locks ({agent_id}.lock)
└── Exclusive lock: For agent state updates
```

### Why Two-Level Locking?

1. **Per-Agent Locks**: Protect individual agent state from concurrent modifications
2. **Global Metadata Lock**: Protects shared metadata file from race conditions

This allows:
- Multiple agents to operate simultaneously (different agent locks)
- Safe metadata updates (global lock prevents conflicts)
- Efficient reads (shared lock allows concurrent reads)

---

## 🔍 Diagnostic Tool

Created `scripts/diagnose_mcp_concurrency.py` to help identify:
- Active lock files
- Metadata file conflicts
- Process conflicts
- Resource contention

**Usage:**
```bash
python3 scripts/diagnose_mcp_concurrency.py
```

---

## 📚 Related Documentation

- **State Locking**: `src/state_locking.py`
- **Too Many Cooks Incident**: `docs/analysis/TOO_MANY_COOKS_INCIDENT.md`
- **Troubleshooting Guide**: `docs/guides/TROUBLESHOOTING.md`

---

## 🎯 Key Takeaways

1. **Shared resources need shared locks** - Per-agent locks weren't enough
2. **Read-modify-write operations need protection** - Metadata updates are atomic now
3. **Lock hierarchy matters** - Global + per-agent locks work together
4. **Diagnostic tools are essential** - Helped identify the root cause quickly

---

**Status:** ✅ Fixed and tested  
**Impact:** Multiple agents can now use MCP simultaneously without conflicts

