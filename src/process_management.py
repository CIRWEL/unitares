"""
Server process management: PID files, lock files, process cleanup.

Extracted from mcp_server.py for maintainability and reuse.
"""

import fcntl
import json
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from src.logging_utils import get_logger

logger = get_logger(__name__)

# Default paths (can be overridden)
_project_root = Path(__file__).parent.parent
SERVER_PID_FILE = _project_root / "data" / ".mcp_server.pid"
SERVER_LOCK_FILE = _project_root / "data" / ".mcp_server.lock"
CURRENT_PID = os.getpid()


def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def cleanup_existing_server_processes():
    """Kill any existing server processes before starting new one."""
    if not SERVER_PID_FILE.exists():
        return []

    killed = []
    try:
        with open(SERVER_PID_FILE, 'r') as f:
            existing_pid = int(f.read().strip())

        if existing_pid != CURRENT_PID and is_process_alive(existing_pid):
            logger.info(f"Found existing server (PID {existing_pid}), terminating...")
            try:
                os.kill(existing_pid, signal.SIGTERM)
                time.sleep(1)
                if is_process_alive(existing_pid):
                    os.kill(existing_pid, signal.SIGKILL)
                killed.append(existing_pid)
                logger.info(f"Terminated existing server (PID {existing_pid})")
            except (OSError, ProcessLookupError):
                pass

        if not is_process_alive(existing_pid):
            SERVER_PID_FILE.unlink(missing_ok=True)
    except (ValueError, IOError) as e:
        logger.warning(f"Could not read existing PID file: {e}")
        SERVER_PID_FILE.unlink(missing_ok=True)

    return killed


def write_server_pid_file():
    """Write PID file for server process tracking."""
    try:
        SERVER_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SERVER_PID_FILE, 'w') as f:
            f.write(f"{CURRENT_PID}\n")
        logger.debug(f"Wrote server PID file: {SERVER_PID_FILE} (PID: {CURRENT_PID})")
    except Exception as e:
        logger.warning(f"Could not write server PID file: {e}", exc_info=True)


def remove_server_pid_file():
    """Remove PID file on shutdown."""
    try:
        if SERVER_PID_FILE.exists():
            SERVER_PID_FILE.unlink()
            logger.debug(f"Removed server PID file: {SERVER_PID_FILE}")
    except Exception as e:
        logger.warning(f"Could not remove server PID file: {e}", exc_info=True)


def acquire_server_lock():
    """Acquire lock file to prevent multiple server instances.

    Automatically cleans up stale locks from dead processes.
    """
    lock_fd = None
    try:
        SERVER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

        if SERVER_LOCK_FILE.exists():
            try:
                with open(SERVER_LOCK_FILE, 'r') as f:
                    lock_info = json.load(f)
                    old_pid = lock_info.get("pid")
                    if old_pid and not is_process_alive(old_pid):
                        logger.info(f"Cleaning up stale lock from dead process (PID: {old_pid})")
                        SERVER_LOCK_FILE.unlink()
            except (json.JSONDecodeError, KeyError, IOError):
                logger.info("Cleaning up corrupt lock file")
                try:
                    SERVER_LOCK_FILE.unlink()
                except FileNotFoundError:
                    pass

        lock_fd = os.open(str(SERVER_LOCK_FILE), os.O_CREAT | os.O_RDWR)

        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            lock_info = {
                "pid": CURRENT_PID,
                "timestamp": time.time(),
                "started_at": datetime.now().isoformat()
            }
            os.ftruncate(lock_fd, 0)
            os.write(lock_fd, json.dumps(lock_info).encode())
            os.fsync(lock_fd)

            logger.debug(f"Acquired server lock file: {SERVER_LOCK_FILE} (PID: {CURRENT_PID})")
            return lock_fd
        except IOError:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
            raise RuntimeError(
                f"Server is already running (lock file: {SERVER_LOCK_FILE}). "
                f"Only one server instance can run at a time."
            )
    except RuntimeError:
        raise
    except Exception as e:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except (OSError, ValueError):
                pass
        logger.warning(f"Could not acquire server lock: {e}", exc_info=True)
        return None


def release_server_lock(lock_fd):
    """Release lock file."""
    if lock_fd is not None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            if SERVER_LOCK_FILE.exists():
                SERVER_LOCK_FILE.unlink()
            logger.debug(f"Released server lock file: {SERVER_LOCK_FILE}")
        except Exception as e:
            logger.warning(f"Could not release server lock: {e}", exc_info=True)
