# Automatic Recovery System

**Created:** 2025-11-25  
**Purpose:** Prevent agents from getting stuck due to lock contention and stale locks

## Overview

This document describes the automatic recovery mechanisms implemented to prevent Cursor agents from getting stuck with error messages. The system now automatically detects and recovers from stale locks, lock contention, and crashed processes without requiring manual intervention.

## Key Features

### 1. Automatic Stale Lock Cleanup

**Location:** `src/state_locking.py`

- **Before Lock Acquisition:** Automatically checks and cleans stale locks before attempting to acquire a lock
- **Process Health Checking:** Verifies that the process holding a lock is still alive
- **Age-Based Detection:** Removes locks older than the stale threshold (default: 60 seconds)

**How it works:**
```python
# Before acquiring lock, system checks:
1. Is lock file present?
2. Is the process (PID) still running?
3. Is the lock timestamp too old?
4. If stale → automatically remove and proceed
```

### 2. Automatic Retry with Exponential Backoff

**Location:** `src/state_locking.py`

- **Retry Logic:** Automatically retries lock acquisition up to 3 times
- **Exponential Backoff:** Waits progressively longer between retries (0.2s, 0.4s, 0.8s)
- **Stale Lock Cleanup Between Retries:** Checks and cleans stale locks before each retry attempt

**Benefits:**
- Handles temporary lock contention gracefully
- Automatically recovers from crashed processes
- Reduces need for manual intervention

### 3. Periodic Background Cleanup

**Location:** `src/mcp_server_std.py`

- **Background Task:** Runs every 5 minutes automatically
- **Proactive Cleanup:** Removes stale locks before they cause issues
- **Non-Blocking:** Runs asynchronously without affecting server performance

**Configuration:**
- Default interval: 300 seconds (5 minutes)
- Stale threshold: 60 seconds
- Can be adjusted via `periodic_lock_cleanup(interval_seconds=...)`

### 4. Enhanced Error Recovery in Core Handler

**Location:** `src/mcp_handlers/core.py`

- **Emergency Cleanup:** If lock acquisition fails after all retries, performs one final aggressive cleanup attempt
- **Better Error Messages:** Provides actionable guidance when locks fail
- **Automatic Recovery:** Attempts to recover before returning error to user

**Error Message Example:**
```
Failed to acquire lock for agent 'agent_id' after automatic retries and cleanup. 
This usually means another active process is updating this agent. 
The system has automatically cleaned stale locks. If this persists, try: 
1) Wait a few seconds and retry, 2) Check for other Cursor/Claude sessions, 
3) Use cleanup_stale_locks tool, or 4) Restart Cursor if stuck.
```

## Technical Details

### Lock Staleness Detection

A lock is considered stale if:
1. The process (PID) recorded in the lock file is no longer running
2. The lock file is corrupted or unreadable
3. The lock timestamp is older than the threshold AND the process is dead

### Process Health Checking

Uses `os.kill(pid, 0)` to check if a process is alive:
- Signal 0 doesn't kill the process, just checks existence
- Works on Unix-like systems (macOS, Linux)
- Falls back gracefully if process check fails

### Retry Strategy

```
Attempt 1: Try to acquire lock (timeout: 5s)
  ↓ If fails
Check for stale lock → Clean if stale → Wait 0.2s

Attempt 2: Try to acquire lock (timeout: 5s)
  ↓ If fails
Check for stale lock → Clean if stale → Wait 0.4s

Attempt 3: Try to acquire lock (timeout: 5s)
  ↓ If fails
Emergency cleanup → Return error with guidance
```

## Configuration

### Lock Manager Settings

```python
StateLockManager(
    auto_cleanup_stale=True,      # Enable automatic stale lock cleanup
    stale_threshold=60.0           # Seconds before considering lock stale
)
```

### Lock Acquisition Settings

```python
acquire_agent_lock(
    agent_id="agent_id",
    timeout=5.0,                  # Timeout per retry attempt
    max_retries=3                 # Maximum retry attempts
)
```

### Periodic Cleanup Settings

```python
periodic_lock_cleanup(
    interval_seconds=300          # Run every 5 minutes
)
```

## Benefits

1. **No Manual Intervention Required:** System automatically recovers from most lock issues
2. **Faster Recovery:** Stale locks are cleaned immediately when detected
3. **Better User Experience:** Clear error messages with actionable guidance
4. **Proactive Prevention:** Background cleanup prevents issues before they occur
5. **Resilient:** Handles crashes, process kills, and system restarts gracefully

## Migration Notes

- **Backward Compatible:** All changes are backward compatible
- **No Breaking Changes:** Existing code continues to work
- **Automatic:** No configuration required - works out of the box

## Troubleshooting

If agents still get stuck (rare):

1. **Check for Active Processes:**
   ```bash
   ps aux | grep mcp_server_std.py
   ```

2. **Manual Lock Cleanup:**
   ```python
   # Use the cleanup_stale_locks tool
   cleanup_stale_locks(max_age_seconds=60, dry_run=False)
   ```

3. **Check Lock Files:**
   ```bash
   ls -la data/locks/
   ```

4. **Restart Cursor:** If all else fails, restart Cursor to clear all locks

## Future Enhancements

Potential improvements:
- Lock priority system for critical operations
- Distributed lock coordination for multi-machine setups
- Lock metrics and monitoring
- Adaptive timeout based on system load

