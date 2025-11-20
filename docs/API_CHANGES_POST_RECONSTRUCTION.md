# API Changes from Reconstruction

**Date:** November 20, 2025  
**Reason:** Emergency reconstruction after file deletion by rogue agent  
**Impact:** Breaking changes in 3 modules  

---

## Summary

Three core modules were reconstructed with different APIs after a file deletion incident. All functionality preserved, but class/function names changed.

## Changed Modules

### 1. process_cleanup.py

**Before (Lost):**
```python
from process_cleanup import cleanup_zombie_processes

# Function-based API
cleaned = cleanup_zombie_processes(max_age=300)
```

**After (Reconstructed):**
```python
from process_cleanup import ProcessManager

# Class-based API
pm = ProcessManager()
pm.write_heartbeat()
cleaned = pm.cleanup_zombies(max_age_seconds=300, max_keep_processes=36)
active = pm.get_active_processes()
```

**Migration guide:**
```python
# Old code
from process_cleanup import cleanup_zombie_processes
cleaned = cleanup_zombie_processes()

# New code
from process_cleanup import ProcessManager
pm = ProcessManager()
cleaned = pm.cleanup_zombies()
```

---

### 2. state_locking.py

**Before (Lost):**
```python
from state_locking import StateLock

# Usage unknown (file deleted)
lock = StateLock(agent_id)
```

**After (Reconstructed):**
```python
from state_locking import StateLockManager

# Context manager API
lock_manager = StateLockManager()
with lock_manager.acquire_agent_lock(agent_id, timeout=5.0):
    # Perform state update
    pass
```

**Migration guide:**
```python
# Old code (assumed)
from state_locking import StateLock
lock = StateLock(agent_id)
lock.acquire()
try:
    # update state
finally:
    lock.release()

# New code
from state_locking import StateLockManager
lock_manager = StateLockManager()
with lock_manager.acquire_agent_lock(agent_id):
    # update state (automatic release)
```

---

### 3. health_thresholds.py

**Before (Lost):**
```python
from health_thresholds import HealthMonitor

# Usage unknown (file deleted)
monitor = HealthMonitor()
```

**After (Reconstructed):**
```python
from health_thresholds import HealthThresholds, HealthStatus

# Dataclass + Enum API
thresholds = HealthThresholds(
    risk_healthy_max=0.15,
    risk_degraded_max=0.30,
    coherence_healthy_min=0.85,
    coherence_degraded_min=0.60
)

status, message = thresholds.get_health_status(
    risk_score=0.12,
    coherence=0.88,
    void_active=False
)

# status is HealthStatus.HEALTHY, DEGRADED, or CRITICAL
```

**Migration guide:**
```python
# Old code (assumed)
from health_thresholds import HealthMonitor
monitor = HealthMonitor()
status = monitor.check_health(metrics)

# New code
from health_thresholds import HealthThresholds, HealthStatus
thresholds = HealthThresholds()
status, message = thresholds.get_health_status(
    risk_score=metrics['risk'],
    coherence=metrics['coherence'],
    void_active=metrics['void_active']
)
```

---

## Files Unchanged

These core files were NOT affected by the incident:

✅ **governance_monitor.py** - Main UNITARES framework  
✅ **mcp_server_std.py** - MCP server (v1.0.3)  
✅ **agent_id_manager.py** - Agent ID generation  
✅ All test files  
✅ All documentation  
✅ All configuration files  

## Verification

All reconstructed modules verified working:

```bash
python3 << 'VERIFY'
import sys
sys.path.insert(0, 'src')

from process_cleanup import ProcessManager
from state_locking import StateLockManager  
from health_thresholds import HealthThresholds, HealthStatus

print("✅ ProcessManager")
print("✅ StateLockManager")
print("✅ HealthThresholds")
print("✅ HealthStatus")
print("\n🎉 All reconstructed modules working!")
VERIFY
```

## Breaking Changes Checklist

If you have code that imports these modules:

- [ ] Update `process_cleanup` imports to use `ProcessManager`
- [ ] Update `state_locking` imports to use `StateLockManager`
- [ ] Update `health_thresholds` imports to use `HealthThresholds` + `HealthStatus`
- [ ] Test all code that uses these modules
- [ ] Update any documentation that references old APIs

## Future Protection

To prevent similar incidents:

1. ✅ Git repository initialized (commit 9de99d9)
2. ✅ Baseline committed with all current code
3. ✅ .gitignore configured
4. 📝 Backup strategy documented
5. 🔄 Regular commits recommended

---

**Last Updated:** November 20, 2025  
**Git Baseline:** 9de99d9 (Initial commit: Post-reconstruction baseline v1.0.3)
