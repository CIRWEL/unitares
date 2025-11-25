"""
State Locking Manager for Multi-Process Coordination

Ensures only one process can modify agent state at a time using file-based locking.
Prevents race conditions and state corruption in multi-process MCP environments.

Features:
- Automatic stale lock cleanup before acquisition attempts
- Exponential backoff retry with automatic recovery
- Process health checking to detect stale locks
"""

import fcntl
import os
import time
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, Any


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running"""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
        return True
    except (OSError, ProcessLookupError):
        return False


class StateLockManager:
    """Ensures only one process can modify agent state at a time"""
    
    def __init__(self, lock_dir: Path = None, auto_cleanup_stale: bool = True, stale_threshold: float = 60.0):
        if lock_dir is None:
            # Use project data directory for locks
            project_root = Path(__file__).parent.parent
            lock_dir = project_root / "data" / "locks"
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.auto_cleanup_stale = auto_cleanup_stale
        self.stale_threshold = stale_threshold  # Seconds before considering lock stale
        
    def _check_and_clean_stale_lock(self, lock_file: Path) -> bool:
        """
        Check if lock file is stale and clean it if so.
        Returns True if lock was cleaned, False otherwise.
        """
        if not lock_file.exists():
            return False
        
        try:
            # Try to read lock info
            with open(lock_file, 'r') as f:
                try:
                    lock_data = json.load(f)
                    pid = lock_data.get('pid')
                    timestamp = lock_data.get('timestamp', 0)
                    
                    if pid is None:
                        # No PID means stale/corrupted
                        lock_file.unlink(missing_ok=True)
                        return True
                    
                    # Check if process is alive
                    if not is_process_alive(pid):
                        # Process is dead, lock is stale
                        lock_file.unlink(missing_ok=True)
                        return True
                    
                    # Check if lock timestamp is too old
                    if timestamp > 0:
                        lock_age = time.time() - timestamp
                        if lock_age > self.stale_threshold:
                            # Lock is old, but process might still be alive
                            # Double-check process is actually dead
                            if not is_process_alive(pid):
                                lock_file.unlink(missing_ok=True)
                                return True
                    
                except (json.JSONDecodeError, ValueError):
                    # Corrupted lock file
                    lock_file.unlink(missing_ok=True)
                    return True
        except IOError:
            # Can't read lock file, might be locked by another process
            # Don't delete it - it's actively held
            return False
        
        return False
    
    @contextmanager
    def acquire_agent_lock(self, agent_id: str, timeout: float = 5.0, max_retries: int = 3):
        """
        Acquire exclusive lock for agent state updates with automatic recovery.
        
        Args:
            agent_id: Agent identifier
            timeout: Timeout per retry attempt in seconds
            max_retries: Maximum number of retry attempts with cleanup
        """
        lock_file = self.lock_dir / f"{agent_id}.lock"
        lock_fd = None
        
        # Automatic stale lock cleanup before attempting acquisition
        if self.auto_cleanup_stale:
            try:
                self._check_and_clean_stale_lock(lock_file)
            except Exception:
                # Non-critical, continue with lock acquisition
                pass
        
        # Retry loop with exponential backoff and automatic cleanup
        last_error = None
        for attempt in range(max_retries):
            start_time = time.time()
            lock_fd = None
            
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
                        
                        # Lock acquired successfully - yield control
                        try:
                            yield  # Lock acquired, allow operation
                        finally:
                            # Always release lock when exiting context
                            try:
                                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                            except:
                                pass
                            os.close(lock_fd)
                        return  # Success, exit retry loop
                    except IOError:
                        # Lock is held by another process, wait and retry
                        time.sleep(0.1)
                
                # Timeout reached - close file descriptor before retry
                if lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except:
                        pass
                    os.close(lock_fd)
                    lock_fd = None
                
                # Before retrying, check if lock is stale and clean it
                if attempt < max_retries - 1:  # Don't clean on last attempt
                    if self.auto_cleanup_stale:
                        try:
                            cleaned = self._check_and_clean_stale_lock(lock_file)
                            if cleaned:
                                # Wait a bit before retrying after cleanup
                                time.sleep(0.2)
                        except Exception:
                            pass
                    
                    # Exponential backoff: wait longer on each retry
                    wait_time = 0.2 * (2 ** attempt)
                    time.sleep(wait_time)
                    
            except Exception as e:
                # Close file descriptor on error
                if lock_fd:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except:
                        pass
                    os.close(lock_fd)
                    lock_fd = None
                
                last_error = e
                
                # If this is the last attempt, break to raise error
                if attempt == max_retries - 1:
                    break
                
                # Otherwise, wait and retry
                time.sleep(0.2 * (2 ** attempt))
        
        # All retries exhausted - raise appropriate error
        if last_error:
            raise last_error
        else:
            raise TimeoutError(
                f"Could not acquire lock for agent '{agent_id}' after {max_retries} attempts "
                f"(timeout: {timeout}s each). Lock may be held by another active process. "
                f"Try running cleanup_stale_locks tool or check for stuck processes."
            )

