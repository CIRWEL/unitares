"""
Agent monitor state management.

Monitor instances, state file I/O (save/load), per-agent state persistence.
"""

from __future__ import annotations

import os
import json
import time
import fcntl
import asyncio
from pathlib import Path

from src.logging_utils import get_logger
from src.agent_metadata_model import project_root
from src.governance_monitor import UNITARESMonitor

logger = get_logger(__name__)

# Store monitors per agent (shared mutable dict)
monitors: dict[str, UNITARESMonitor] = {}


def get_state_file(agent_id: str) -> Path:
    """
    Get path to state file for an agent.

    Uses organized structure: data/agents/{agent_id}_state.json

    Provides automatic migration: if file exists in old location (data/ root),
    it will be automatically moved to new location on first access.
    """
    new_path = Path(project_root) / "data" / "agents" / f"{agent_id}_state.json"
    old_path = Path(project_root) / "data" / f"{agent_id}_state.json"

    if not new_path.exists() and old_path.exists():
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            logger.info(f"Migrated {agent_id} state file to agents/ subdirectory")
        except Exception as e:
            logger.warning(f"Could not migrate {agent_id} state file: {e}", exc_info=True)
            return old_path

    return new_path


def _write_state_file(state_file: Path, state_data: dict) -> None:
    """Helper function to write state file (used by both sync and async versions)"""
    with open(state_file, 'w') as f:
        json.dump(state_data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


async def save_monitor_state_async(agent_id: str, monitor: UNITARESMonitor) -> None:
    """
    Async version of save_monitor_state - uses file-based storage.

    Uses async file locking to avoid blocking the event loop.
    """
    state_data = monitor.state.to_dict_with_history()

    state_file = get_state_file(agent_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state_lock_file = state_file.parent / f".{agent_id}_state.lock"

    lock_fd = None
    try:
        lock_fd = os.open(str(state_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0

        try:
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    await asyncio.sleep(0.1)

            if not lock_acquired:
                logger.warning(f"State lock timeout for {agent_id} ({timeout}s)")
                raise TimeoutError("State lock timeout")

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _write_state_file, state_file, state_data)

        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Could not acquire state lock for {agent_id}: {e}", exc_info=True)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _write_state_file, state_file, state_data)
        except Exception as fallback_error:
            logger.error(f"Failed to save state even without lock for {agent_id}: {fallback_error}", exc_info=True)


def save_monitor_state(agent_id: str, monitor: UNITARESMonitor) -> None:
    """Save monitor state to file with locking to prevent race conditions."""
    state_data = monitor.state.to_dict_with_history()

    state_file = get_state_file(agent_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state_lock_file = state_file.parent / f".{agent_id}_state.lock"

    lock_fd = None
    try:
        lock_fd = os.open(str(state_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0

        try:
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    time.sleep(0.1)

            if not lock_acquired:
                logger.warning(f"State lock timeout for {agent_id} ({timeout}s)")
                raise TimeoutError("State lock timeout")

            _write_state_file(state_file, state_data)

        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except (IOError, OSError):
                    pass
                try:
                    os.close(lock_fd)
                except (OSError, ValueError):
                    pass
    except Exception as e:
        logger.warning(f"Could not acquire state lock for {agent_id}: {e}", exc_info=True)
        try:
            _write_state_file(state_file, state_data)
        except Exception as e2:
            logger.error(f"Could not save state for {agent_id}: {e2}", exc_info=True)


def load_monitor_state(agent_id: str) -> 'GovernanceState | None':
    """Load monitor state from file if it exists."""
    from src.governance_state import GovernanceState

    state_file = get_state_file(agent_id)

    if not state_file.exists():
        return None

    try:
        with open(state_file, 'r') as f:
            data = json.load(f)
            state = GovernanceState.from_dict(data)
            return state
    except Exception as e:
        logger.warning(f"Could not load state for {agent_id}: {e}", exc_info=True)
        return None
