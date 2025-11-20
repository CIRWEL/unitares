# Priority Refinements

## 1. Process Management

- [x] Add psutil dependency (installed, but needs runtime verification)
- [x] Implement zombie cleanup on startup (implemented in v1.0.2)
- [ ] Add process heartbeat mechanism
- [ ] Add process health monitoring
- [ ] Implement graceful shutdown handling

**Status**: Basic cleanup implemented. Needs heartbeat and health monitoring.

## 2. Consistency Layer

- [ ] Add file-based locking for single writer
- [ ] Implement state versioning
- [ ] Add conflict resolution for concurrent updates
- [ ] Add metadata file atomic writes
- [ ] Implement transaction-like updates

**Status**: Not implemented. Critical for multi-process safety.

## 3. Health Thresholds

- [ ] healthy: risk < 0.15
- [ ] degraded: 0.15 <= risk < 0.30  
- [ ] critical: risk >= 0.30
- [ ] Add coherence thresholds
- [ ] Add void state thresholds
- [ ] Implement health-based alerting

**Status**: Current thresholds are coherence-based. Risk-based thresholds need implementation.

## 4. Testing Suite

- [ ] Chaos testing (random restarts)
- [ ] Concurrent update tests
- [ ] Recovery scenario tests
- [ ] Multi-process coordination tests
- [ ] State persistence tests
- [ ] NaN/inf propagation tests

**Status**: No formal test suite exists. Critical for production readiness.

---

## Specific Code Improvements

### 1. Add Process Management

```python
# In server initialization (src/mcp_server_std.py)
import psutil
import fcntl
import time
from pathlib import Path

def cleanup_zombie_processes():
    """Remove orphaned MCP processes on startup"""
    if not PSUTIL_AVAILABLE:
        return
    
    current_pid = os.getpid()
    stale_processes = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline and any('mcp_server_std.py' in str(arg) for arg in cmdline):
                pid = proc.info['pid']
                if pid != current_pid:
                    # Check if process is actually responding
                    if not is_process_healthy(pid):
                        stale_processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    for proc in stale_processes:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except psutil.TimeoutExpired:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

def is_process_healthy(pid: int) -> bool:
    """Check if process is responding to heartbeats"""
    # Check PID file timestamp
    pid_file = Path(project_root) / "data" / f".mcp_server_{pid}.heartbeat"
    if not pid_file.exists():
        return False
    
    # Check if heartbeat is recent (within 30 seconds)
    try:
        last_heartbeat = pid_file.stat().st_mtime
        return (time.time() - last_heartbeat) < 30
    except:
        return False

def update_heartbeat():
    """Update heartbeat file for this process"""
    heartbeat_file = Path(project_root) / "data" / f".mcp_server_{CURRENT_PID}.heartbeat"
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_file.touch()
```

### 2. Implement State Locking

```python
import fcntl
import time
from contextlib import contextmanager

def acquire_state_lock(agent_id: str, timeout: float = 5.0) -> contextmanager:
    """Distributed lock for agent state updates using file-based locking"""
    lock_file = Path(project_root) / "data" / f".lock_{agent_id}"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def lock():
        lock_fd = None
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                lock_fd = open(lock_file, 'w')
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_fd.write(f"{os.getpid()}\n{time.time()}\n")
                lock_fd.flush()
                yield
                break
            except (IOError, OSError):
                if lock_fd:
                    lock_fd.close()
                time.sleep(0.1)
        else:
            raise TimeoutError(f"Could not acquire lock for {agent_id} within {timeout}s")
        finally:
            if lock_fd:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
                try:
                    lock_file.unlink()
                except:
                    pass
    
    return lock()

# Usage in process_agent_update:
async def call_tool(name: str, arguments: dict[str, Any] | None):
    if name == "process_agent_update":
        agent_id = arguments.get("agent_id", "default_agent")
        
        with acquire_state_lock(agent_id):
            monitor, error = get_agent_or_error(agent_id)
            if error:
                return error_response(error)
            
            # Process update atomically
            result = monitor.process_update(...)
            save_metadata()  # Atomic write
            return success_response(result)
```

### 3. Add Health Thresholds

```python
# In config/governance_config.py or src/mcp_server_std.py

class HealthThresholds:
    """Health status thresholds based on risk and coherence"""
    
    # Risk-based thresholds
    RISK_HEALTHY = 0.15
    RISK_DEGRADED = 0.30
    
    # Coherence thresholds
    COHERENCE_HEALTHY = 0.85
    COHERENCE_DEGRADED = 0.60
    
    # Void state threshold
    VOID_CRITICAL = True  # Any void_active is critical
    
    @staticmethod
    def calculate_health(risk: float, coherence: float, void_active: bool) -> str:
        """Calculate health status from metrics"""
        if void_active:
            return 'critical'
        
        if risk >= HealthThresholds.RISK_DEGRADED:
            return 'critical'
        elif risk >= HealthThresholds.RISK_HEALTHY:
            return 'degraded'
        
        if coherence < HealthThresholds.COHERENCE_DEGRADED:
            return 'critical'
        elif coherence < HealthThresholds.COHERENCE_HEALTHY:
            return 'degraded'
        
        return 'healthy'

# Update list_agents to use new thresholds:
health_status = HealthThresholds.calculate_health(
    risk=state.risk_score,
    coherence=state.coherence,
    void_active=state.void_active
)
```

### 4. Add Integration Tests

```python
# tests/test_concurrent_updates.py
import asyncio
import pytest
from src.governance_monitor import UNITARESMonitor

async def test_concurrent_updates():
    """Test multiple updates don't corrupt state"""
    agent_id = "test_concurrent_agent"
    
    # Create monitor
    monitor = UNITARESMonitor(agent_id)
    
    # Simulate concurrent updates
    tasks = [
        monitor.process_update(
            agent_id=agent_id,
            parameters=[0.5] * 128,
            ethical_drift=[0.0, 0.0, 0.0],
            response_text=f"Update {i}",
            complexity=0.5
        )
        for i in range(10)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Verify all succeeded
    assert all(not isinstance(r, Exception) for r in results)
    
    # Verify state consistency
    assert monitor.state.update_count == 10
    assert len(monitor.state.V_history) == 10
    assert len(monitor.state.coherence_history) == 10
    
    # Verify no NaN/inf values
    assert not any(
        math.isnan(v) or math.isinf(v)
        for v in [
            monitor.state.E, monitor.state.I, monitor.state.S, monitor.state.V,
            monitor.state.coherence, monitor.state.lambda1
        ]
    )

async def test_chaos_restart():
    """Test system recovery after random restarts"""
    agent_id = "test_chaos_agent"
    
    # Process some updates
    monitor = UNITARESMonitor(agent_id)
    for i in range(5):
        monitor.process_update(...)
    
    # Simulate restart (reload from metadata)
    # ... reload logic ...
    
    # Verify state persisted correctly
    assert monitor.state.update_count == 5

async def test_recovery_scenario():
    """Test recovery from coherence collapse"""
    agent_id = "test_recovery_agent"
    monitor = UNITARESMonitor(agent_id)
    
    # Induce coherence collapse
    for i in range(10):
        monitor.process_update(
            parameters=[random.random()] * 128,  # Random params = low coherence
            ethical_drift=[0.1, 0.1, 0.1],  # High drift
            ...
        )
    
    # Verify system attempts recovery
    assert monitor.state.lambda1 < 0.15  # Adaptive control should reduce λ₁
    
    # Process good updates
    for i in range(10):
        monitor.process_update(
            parameters=[0.5] * 128,  # Consistent params
            ethical_drift=[0.0, 0.0, 0.0],  # No drift
            ...
        )
    
    # Verify recovery
    assert monitor.state.coherence > 0.8  # Should recover
    assert monitor.state.lambda1 > 0.10  # Should increase back
```

---

## Implementation Priority

1. **High Priority** (Production blockers):
   - State locking for consistency
   - Health thresholds implementation
   - Process heartbeat mechanism

2. **Medium Priority** (Quality improvements):
   - Comprehensive test suite
   - Enhanced process cleanup
   - State versioning

3. **Low Priority** (Nice to have):
   - Advanced conflict resolution
   - Health-based alerting
   - Performance optimizations

---

## Notes

- Current system works but lacks multi-process coordination
- File-based locking is simplest approach (no external dependencies)
- Health thresholds should be configurable
- Test suite should cover edge cases discovered during development (NaN propagation, zombie processes, etc.)

