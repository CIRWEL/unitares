"""
State Locking Manager for Multi-Process Coordination

Ensures only one process can modify agent state at a time using file-based locking.
Prevents race conditions and state corruption in multi-process MCP environments.
"""

import fcntl
import os
import time
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, Any


class StateLockManager:
    """Ensures only one process can modify agent state at a time"""
    
    def __init__(self, lock_dir: Path = None):
        if lock_dir is None:
            # Use project data directory for locks
            project_root = Path(__file__).parent.parent
            lock_dir = project_root / "data" / "locks"
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        
    @contextmanager
    def acquire_agent_lock(self, agent_id: str, timeout: float = 5.0):
        """Acquire exclusive lock for agent state updates"""
        lock_file = self.lock_dir / f"{agent_id}.lock"
        lock_fd = None
        start_time = time.time()
        
        try:
            # Create lock file if doesn't exist
            lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR)
            
            # Try to acquire lock with timeout
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Write PID and timestamp to lock file for debugging
                    lock_info = {
                        "pid": os.getpid(),
                        "timestamp": time.time(),
                        "agent_id": agent_id
                    }
                    os.ftruncate(lock_fd, 0)  # Clear file
                    os.write(lock_fd, json.dumps(lock_info).encode())
                    os.fsync(lock_fd)  # Ensure written to disk
                    yield  # Lock acquired, allow operation
                    break
                except IOError:
                    # Lock is held by another process, wait and retry
                    time.sleep(0.1)
            else:
                # Timeout reached
                raise TimeoutError(
                    f"Could not acquire lock for agent '{agent_id}' after {timeout}s. "
                    f"Another process may be updating this agent."
                )
                
        finally:
            if lock_fd:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except:
                    pass
                os.close(lock_fd)
                # Optionally remove lock file (or keep for debugging)
                # lock_file.unlink(missing_ok=True)

