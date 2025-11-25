#!/usr/bin/env python3
"""
UNITARES Governance MCP Server v1.0 - Standard MCP Protocol Implementation

This is a proper MCP server implementation that follows the Model Context Protocol specification.
It can be used with Cursor (Composer), Claude Desktop, and other MCP-compatible clients.

Usage:
    python src/mcp_server_std.py

Configuration:
    Add to Cursor MCP config (for Composer) or Claude Desktop MCP config
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Any, Sequence
import traceback
import signal
import atexit
import os
import time
import fcntl
import secrets
import base64

try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    AIOFILES_AVAILABLE = False
    print("[UNITARES MCP] Warning: aiofiles not available. File I/O will be synchronous. Install with: pip install aiofiles", file=sys.stderr)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[UNITARES MCP] Warning: psutil not available. Process cleanup disabled. Install with: pip install psutil", file=sys.stderr)

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_SDK_AVAILABLE = True
except ImportError as e:
    MCP_SDK_AVAILABLE = False
    print(f"Error: MCP SDK not available: {e}", file=sys.stderr)
    print(f"Python: {sys.executable}", file=sys.stderr)
    print(f"PYTHONPATH: {sys.path}", file=sys.stderr)
    print("Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

from src.governance_monitor import UNITARESMonitor
from src.state_locking import StateLockManager
from src.health_thresholds import HealthThresholds, HealthStatus
from src.process_cleanup import ProcessManager
from src.pattern_analysis import analyze_agent_patterns
from src.runtime_config import get_thresholds
from src.lock_cleanup import cleanup_stale_state_locks
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import os

# Server version - increment when making breaking changes or critical fixes
SERVER_VERSION = "2.0.0"  # UNITARES v2.0: Architecture unification with governance_core
SERVER_BUILD_DATE = "2025-11-22"

# PID file for process tracking
PID_FILE = Path(project_root) / "data" / ".mcp_server.pid"
LOCK_FILE = Path(project_root) / "data" / ".mcp_server.lock"

# Maximum number of processes to keep before cleanup
# Increase this if you have many active MCP clients
# Increased to 72 (2x from 36, originally 9)
MAX_KEEP_PROCESSES = 72

# Create MCP server instance
server = Server("governance-monitor-v1")

# Current process PID
CURRENT_PID = os.getpid()

# Log startup with version and PID for debugging multi-process issues
print(f"[UNITARES MCP v{SERVER_VERSION}] Server starting (PID: {CURRENT_PID}, Build: {SERVER_BUILD_DATE})", file=sys.stderr)

# Initialize managers for state locking, health thresholds, and process management
lock_manager = StateLockManager()
health_checker = HealthThresholds()
process_mgr = ProcessManager()

# Store monitors per agent
monitors: dict[str, UNITARESMonitor] = {}


@dataclass
class AgentMetadata:
    """Agent lifecycle metadata"""
    agent_id: str
    status: str  # "active", "paused", "archived", "deleted"
    created_at: str  # ISO format
    last_update: str  # ISO format
    version: str = "v1.0"
    total_updates: int = 0
    tags: list[str] = None
    notes: str = ""
    lifecycle_events: list[dict] = None
    paused_at: str = None
    archived_at: str = None
    parent_agent_id: str = None  # If spawned from another agent
    spawn_reason: str = None  # Reason for spawning (e.g., "new_domain", "parent_archived")
    api_key: str = None  # API key for authentication (generated on creation)
    # Loop detection tracking
    recent_update_timestamps: list[str] = None  # ISO timestamps of recent updates
    recent_decisions: list[str] = None  # Recent decision actions (approve/revise/reject)
    loop_detected_at: str = None  # ISO timestamp when loop was detected
    loop_cooldown_until: str = None  # ISO timestamp until which updates are blocked

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.lifecycle_events is None:
            self.lifecycle_events = []
        if self.recent_update_timestamps is None:
            self.recent_update_timestamps = []
        if self.recent_decisions is None:
            self.recent_decisions = []

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)

    def add_lifecycle_event(self, event: str, reason: str = None):
        """Add a lifecycle event with timestamp"""
        self.lifecycle_events.append({
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })


# Store agent metadata
agent_metadata: dict[str, AgentMetadata] = {}

# Path to metadata file
METADATA_FILE = Path(project_root) / "data" / "agent_metadata.json"

# State file path template (per-agent)
def get_state_file(agent_id: str) -> Path:
    """Get path to state file for an agent"""
    return Path(project_root) / "data" / f"{agent_id}_state.json"


def load_metadata() -> None:
    """Load agent metadata from file with locking to prevent race conditions"""
    global agent_metadata
    if METADATA_FILE.exists():
        try:
            # Use same lock mechanism as save_metadata, but with timeout to prevent hangs
            metadata_lock_file = METADATA_FILE.parent / ".metadata.lock"
            lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
            lock_acquired = False
            start_time = time.time()
            timeout = 2.0  # Shorter timeout for reads (2 seconds)
            
            try:
                # Try to acquire shared lock with timeout (non-blocking)
                while time.time() - start_time < timeout:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)  # Non-blocking shared lock
                        lock_acquired = True
                        break
                    except IOError:
                        # Lock held by another process, wait and retry
                        time.sleep(0.05)  # Shorter sleep for reads
                
                if not lock_acquired:
                    # Timeout - read without lock (better than hanging)
                    print(f"[UNITARES MCP] Warning: Metadata lock timeout ({timeout}s) for read, reading without lock", file=sys.stderr)
                    # Fall through to read without lock
                else:
                    # Lock acquired, read with lock protection
                    with open(METADATA_FILE, 'r') as f:
                        data = json.load(f)
                        agent_metadata = {}
                        for agent_id, meta in data.items():
                            if 'parent_agent_id' not in meta:
                                meta['parent_agent_id'] = None
                            if 'spawn_reason' not in meta:
                                meta['spawn_reason'] = None
                            if 'recent_update_timestamps' not in meta:
                                meta['recent_update_timestamps'] = None
                            if 'recent_decisions' not in meta:
                                meta['recent_decisions'] = None
                            if 'loop_detected_at' not in meta:
                                meta['loop_detected_at'] = None
                            if 'loop_cooldown_until' not in meta:
                                meta['loop_cooldown_until'] = None
                            agent_metadata[agent_id] = AgentMetadata(**meta)
                    return  # Success, exit early
                
            finally:
                if lock_acquired:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except:
                        pass
                os.close(lock_fd)
            
            # Fallback: read without lock if timeout occurred
            # This is safe for reads - worst case is stale data, but prevents hangs
            with open(METADATA_FILE, 'r') as f:
                data = json.load(f)
                agent_metadata = {}
                for agent_id, meta in data.items():
                    if 'parent_agent_id' not in meta:
                        meta['parent_agent_id'] = None
                    if 'spawn_reason' not in meta:
                        meta['spawn_reason'] = None
                    agent_metadata[agent_id] = AgentMetadata(**meta)
                
        except Exception as e:
            print(f"[UNITARES MCP] Warning: Could not load metadata: {e}", file=sys.stderr)


async def save_metadata_async() -> None:
    """Async version of save_metadata - runs blocking I/O in thread pool"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_metadata)

def save_metadata() -> None:
    """Save agent metadata to file with locking to prevent race conditions"""
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Use a global metadata lock to prevent concurrent writes
    # This is separate from per-agent locks and protects the shared metadata file
    metadata_lock_file = METADATA_FILE.parent / ".metadata.lock"
    
    try:
        # Acquire exclusive lock on metadata file with timeout (prevents hangs)
        lock_fd = os.open(str(metadata_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0  # 5 second timeout (same as agent lock)

        try:
            # Try to acquire lock with timeout (non-blocking)
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    # Lock held by another process, wait and retry
                    time.sleep(0.1)

            if not lock_acquired:
                # Timeout reached - log warning but use fallback
                print(f"[UNITARES MCP] Warning: Metadata lock timeout after {timeout}s, using fallback write", file=sys.stderr)
                raise TimeoutError("Metadata lock timeout")

            # Reload metadata to get latest state from disk (in case another process updated it)
            # Then merge with our in-memory changes (in-memory takes precedence)
            merged_metadata = {}
            if METADATA_FILE.exists():
                try:
                    with open(METADATA_FILE, 'r') as f:
                        existing_data = json.load(f)
                        # Start with what's on disk
                        for agent_id, meta_dict in existing_data.items():
                            merged_metadata[agent_id] = AgentMetadata(**meta_dict)
                except (json.JSONDecodeError, KeyError, TypeError):
                    # If file is corrupted, start fresh
                    pass
            
            # Overwrite with in-memory state (our changes take precedence)
            for agent_id, meta in agent_metadata.items():
                merged_metadata[agent_id] = meta
            
            # Write merged state
            with open(METADATA_FILE, 'w') as f:
                # Sort by agent_id for consistent file output
                data = {
                    agent_id: meta.to_dict()
                    for agent_id, meta in sorted(merged_metadata.items())
                }
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure written to disk
            
            # Update in-memory state with merged result (includes any new agents from disk)
            agent_metadata.update(merged_metadata)
            
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not acquire metadata lock: {e}", file=sys.stderr)
        # Fallback: try without lock (not ideal but better than failing silently)
        with open(METADATA_FILE, 'w') as f:
            data = {
                agent_id: meta.to_dict()
                for agent_id, meta in sorted(agent_metadata.items())
            }
            json.dump(data, f, indent=2)


def get_or_create_metadata(agent_id: str) -> AgentMetadata:
    """Get metadata for agent, creating if needed"""
    if agent_id not in agent_metadata:
        now = datetime.now().isoformat()
        # Generate API key for new agent (authentication)
        api_key = generate_api_key()
        metadata = AgentMetadata(
            agent_id=agent_id,
            status="active",
            created_at=now,
            last_update=now,
            api_key=api_key  # Generate key on creation
        )
        # Add creation lifecycle event
        metadata.add_lifecycle_event("created")

        # Special handling for default agent
        if agent_id == "default_agent":
            metadata.tags.append("pioneer")
            metadata.notes = "First agent - pioneer of the governance system"

        agent_metadata[agent_id] = metadata
        save_metadata()
        
        # Print API key for new agent (one-time display)
        print(f"[UNITARES MCP] Created new agent '{agent_id}'", file=sys.stderr)
        print(f"[UNITARES MCP] API Key: {api_key}", file=sys.stderr)
        print(f"[UNITARES MCP] ⚠️  Save this key - you'll need it for future updates!", file=sys.stderr)
    return agent_metadata[agent_id]


async def save_monitor_state_async(agent_id: str, monitor: UNITARESMonitor) -> None:
    """Async version of save_monitor_state - runs blocking I/O in thread pool"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_monitor_state, agent_id, monitor)

def save_monitor_state(agent_id: str, monitor: UNITARESMonitor) -> None:
    """Save monitor state to file with locking to prevent race conditions"""
    state_file = get_state_file(agent_id)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Use a per-agent state lock to prevent concurrent writes
    state_lock_file = state_file.parent / f".{agent_id}_state.lock"
    
    try:
        # Acquire exclusive lock on state file with timeout
        lock_fd = os.open(str(state_lock_file), os.O_CREAT | os.O_RDWR)
        lock_acquired = False
        start_time = time.time()
        timeout = 5.0  # 5 second timeout

        try:
            # Try to acquire lock with timeout (non-blocking)
            while time.time() - start_time < timeout:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except IOError:
                    # Lock held by another process, wait and retry
                    time.sleep(0.1)

            if not lock_acquired:
                # Timeout reached - log warning but use fallback
                print(f"[UNITARES MCP] Warning: State lock timeout for {agent_id} after {timeout}s, using fallback write", file=sys.stderr)
                raise TimeoutError("State lock timeout")

            # Write state
            state_data = monitor.state.to_dict_with_history()
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())  # Ensure written to disk
            
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not acquire state lock for {agent_id}: {e}", file=sys.stderr)
        # Fallback: try without lock (not ideal but better than failing silently)
        try:
            state_data = monitor.state.to_dict_with_history()
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
        except Exception as e2:
            print(f"[UNITARES MCP] Error: Could not save state for {agent_id}: {e2}", file=sys.stderr)


def load_monitor_state(agent_id: str) -> 'GovernanceState' | None:
    """Load monitor state from file if it exists"""
    state_file = get_state_file(agent_id)
    
    if not state_file.exists():
        return None
    
    try:
        # Read-only access, no lock needed
        with open(state_file, 'r') as f:
            data = json.load(f)
            from src.governance_monitor import GovernanceState
            return GovernanceState.from_dict(data)
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not load state for {agent_id}: {e}", file=sys.stderr)
        return None


# Load metadata on startup
load_metadata()


def auto_archive_old_test_agents(max_age_days: int = 7) -> int:
    """
    Automatically archive old test/demo agents that haven't been updated recently.
    
    Args:
        max_age_days: Archive agents older than this many days (default: 7)
    
    Returns:
        Number of agents archived
    """
    archived_count = 0
    current_time = datetime.now()
    
    for agent_id, meta in list(agent_metadata.items()):
        # Skip if already archived or deleted
        if meta.status in ["archived", "deleted"]:
            continue
        
        # Only archive test/demo agents
        is_test_agent = (
            agent_id.startswith("test_") or 
            agent_id.startswith("demo_") or
            agent_id.startswith("test") or
            "test" in agent_id.lower() or
            "demo" in agent_id.lower()
        )
        
        if not is_test_agent:
            continue
        
        # Check age
        try:
            last_update_dt = datetime.fromisoformat(meta.last_update.replace('Z', '+00:00') if 'Z' in meta.last_update else meta.last_update)
            age_days = (current_time.replace(tzinfo=last_update_dt.tzinfo) if last_update_dt.tzinfo else current_time) - last_update_dt
            age_days = age_days.days
        except:
            # If we can't parse date, skip
            continue
        
        # Archive if old enough
        if age_days >= max_age_days:
            meta.status = "archived"
            meta.archived_at = current_time.isoformat()
            meta.add_lifecycle_event(
                "archived",
                f"Auto-archived: inactive test/demo agent ({age_days} days old, threshold: {max_age_days} days)"
            )
            archived_count += 1
            print(f"[UNITARES MCP] Auto-archived old test agent: {agent_id} ({age_days} days old)", file=sys.stderr)
    
    if archived_count > 0:
        save_metadata()
    
    return archived_count


# Auto-archive old test agents on startup (non-blocking, logs only)
try:
    archived = auto_archive_old_test_agents(max_age_days=7)
    if archived > 0:
        print(f"[UNITARES MCP] Auto-archived {archived} old test/demo agents on startup", file=sys.stderr)

except Exception as e:
    print(f"[UNITARES MCP] Warning: Could not auto-archive old test agents: {e}", file=sys.stderr)

# Clean up stale locks on startup to prevent Cursor freezing
try:
    result = cleanup_stale_state_locks(project_root, max_age_seconds=300, dry_run=False)
    if result['cleaned'] > 0:
        print(f"[UNITARES MCP] Cleaned {result['cleaned']} stale lock files on startup", file=sys.stderr)
except Exception as e:
    print(f"[UNITARES MCP] Warning: Could not clean up stale locks: {e}", file=sys.stderr)


def cleanup_stale_processes():
    """Clean up stale MCP server processes on startup - only if we have too many"""
    if not PSUTIL_AVAILABLE:
        print("[UNITARES MCP] Skipping stale process cleanup (psutil not available)", file=sys.stderr)
        return
    
    try:
        # Find all mcp_server_std.py processes
        current_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and any('mcp_server_std.py' in str(arg) for arg in cmdline):
                    pid = proc.info['pid']
                    if pid != CURRENT_PID:  # Don't kill ourselves
                        create_time = proc.info.get('create_time', 0)
                        age_seconds = time.time() - create_time
                        # Check for heartbeat file to see if process is active
                        heartbeat_file = Path(project_root) / "data" / "processes" / f"heartbeat_{pid}.txt"
                        has_recent_heartbeat = False
                        if heartbeat_file.exists():
                            try:
                                with open(heartbeat_file, 'r') as f:
                                    last_heartbeat = float(f.read())
                                heartbeat_age = time.time() - last_heartbeat
                                has_recent_heartbeat = heartbeat_age < 300  # 5 minutes
                            except (ValueError, IOError):
                                pass
                        
                        current_processes.append({
                            'pid': pid,
                            'create_time': create_time,
                            'age_seconds': age_seconds,
                            'has_recent_heartbeat': has_recent_heartbeat
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Only clean up if we exceed the threshold AND processes are truly stale
        # Don't kill processes that have recent heartbeats (active connections)
        if len(current_processes) > MAX_KEEP_PROCESSES:
            # Sort by creation time (oldest first)
            current_processes.sort(key=lambda x: x['create_time'])
            
            # Only kill processes that:
            # 1. Are older than 5 minutes AND don't have recent heartbeat
            # 2. AND we're over the limit
            stale_processes = [
                p for p in current_processes[:-MAX_KEEP_PROCESSES]  # All except last MAX_KEEP_PROCESSES
                if p['age_seconds'] > 300 and not p['has_recent_heartbeat']
            ]
            
            if stale_processes:
                print(f"[UNITARES MCP] Found {len(current_processes)} server processes, cleaning up {len(stale_processes)} truly stale ones (keeping {MAX_KEEP_PROCESSES} most recent)...", file=sys.stderr)
                
                for proc_info in stale_processes:
                    try:
                        proc = psutil.Process(proc_info['pid'])
                        age_minutes = int(proc_info['age_seconds'] / 60)
                        print(f"[UNITARES MCP] Killing stale process PID {proc_info['pid']} (age: {age_minutes}m, no recent heartbeat)", file=sys.stderr)
                        proc.terminate()
                        # Give it a moment to clean up
                        try:
                            proc.wait(timeout=2)
                        except psutil.TimeoutExpired:
                            proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        print(f"[UNITARES MCP] Could not kill PID {proc_info['pid']}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not clean stale processes: {e}", file=sys.stderr)


def write_pid_file():
    """Write PID file for process tracking"""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(f"{CURRENT_PID}\n{SERVER_VERSION}\n{time.time()}\n")
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not write PID file: {e}", file=sys.stderr)


def remove_pid_file():
    """Remove PID file on shutdown"""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception as e:
        print(f"[UNITARES MCP] Warning: Could not remove PID file: {e}", file=sys.stderr)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print(f"\n[UNITARES MCP] Received signal {signum}, shutting down gracefully...", file=sys.stderr)
    remove_pid_file()
    sys.exit(0)


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Register cleanup on exit
atexit.register(remove_pid_file)

# Write heartbeat immediately on startup to mark this process as active
# This prevents other clients from killing this process during their cleanup
process_mgr.write_heartbeat()

# Clean up stale processes on startup (using ProcessManager)
# Use longer max_age to avoid killing active connections from other clients
# Only kill processes that are truly stale (5+ minutes old without heartbeat)
try:
    cleaned = process_mgr.cleanup_zombies(max_age_seconds=300, max_keep_processes=MAX_KEEP_PROCESSES)
    if cleaned:
        print(f"[UNITARES MCP] Cleaned up {len(cleaned)} zombie processes on startup", file=sys.stderr)
except Exception as e:
    print(f"[UNITARES MCP] Warning: Could not clean zombies on startup: {e}", file=sys.stderr)

# Clean up stale lock files (from crashed/killed processes)
try:
    from lock_cleanup import cleanup_stale_state_locks
    lock_cleanup_result = cleanup_stale_state_locks(project_root=project_root, max_age_seconds=300, dry_run=False)
    if lock_cleanup_result['cleaned'] > 0:
        print(f"[UNITARES MCP] Cleaned up {lock_cleanup_result['cleaned']} stale lock file(s) on startup", file=sys.stderr)
except Exception as e:
    print(f"[UNITARES MCP] Warning: Could not clean stale locks on startup: {e}", file=sys.stderr)

# Also run legacy cleanup for compatibility (but only if we have too many processes)
# Don't kill processes aggressively - let multiple clients coexist
cleanup_stale_processes()

# Write PID file
write_pid_file()


def spawn_agent_with_inheritance(
    new_agent_id: str,
    parent_agent_id: str,
    spawn_reason: str = "spawned",
    inheritance_factor: float = 0.7
) -> UNITARESMonitor:
    """
    Spawn a new agent with inherited state from parent.
    
    Args:
        new_agent_id: ID for the new agent
        parent_agent_id: ID of parent agent to inherit from
        spawn_reason: Reason for spawning (e.g., "new_domain", "parent_archived")
        inheritance_factor: How much state to inherit (0.0-1.0, default 0.7 = 70%)
    
    Returns:
        New UNITARESMonitor with inherited state
    """
    # Check parent exists
    if parent_agent_id not in agent_metadata:
        raise ValueError(f"Parent agent '{parent_agent_id}' not found")
    
    # Get or create parent monitor to access state
    parent_monitor = get_or_create_monitor(parent_agent_id)
    parent_state = parent_monitor.state
    parent_meta = agent_metadata[parent_agent_id]
    
    # Create new monitor
    new_monitor = UNITARESMonitor(new_agent_id, load_state=False)
    new_state = new_monitor.state
    
    # Inherit thermodynamic state (scaled by inheritance_factor)
    new_state.E = parent_state.E * inheritance_factor + (1 - inheritance_factor) * 0.5
    new_state.I = parent_state.I * inheritance_factor + (1 - inheritance_factor) * 0.5
    new_state.S = parent_state.S * (1 - inheritance_factor * 0.5)  # Reset entropy more
    new_state.V = parent_state.V * inheritance_factor * 0.5  # Reset void more
    
    # Inherit coherence (scaled)
    new_state.coherence = parent_state.coherence * inheritance_factor + (1 - inheritance_factor) * 1.0
    
    # Inherit lambda1 (scaled toward default)
    from config.governance_config import GovernanceConfig
    config = GovernanceConfig()
    default_lambda1 = (config.LAMBDA1_MIN + config.LAMBDA1_MAX) / 2
    new_state.lambda1 = parent_state.lambda1 * inheritance_factor + default_lambda1 * (1 - inheritance_factor)
    
    # Inherit risk (scaled down, but with minimum based on parent)
    parent_risk = getattr(parent_state, 'risk_score', None)
    if parent_risk is not None:
        # Inherit 50% of parent risk, but cap at 15% initial
        inherited_risk = min(parent_risk * 0.5, 0.15)
        # If parent was critical, new agent starts with at least 5% risk
        if parent_risk >= 0.30:
            inherited_risk = max(inherited_risk, 0.05)
        new_state.risk_score = inherited_risk
    
    # Copy some history (scaled down)
    history_length = min(len(parent_state.V_history), 100)  # Max 100 entries
    if history_length > 0:
        new_state.V_history = parent_state.V_history[-history_length:].copy()
        new_state.coherence_history = parent_state.coherence_history[-history_length:].copy() if hasattr(parent_state, 'coherence_history') else []
        new_state.risk_history = parent_state.risk_history[-history_length:].copy() if hasattr(parent_state, 'risk_history') else []
    
    # Create metadata with spawn tracking
    now = datetime.now().isoformat()
    new_meta = AgentMetadata(
        agent_id=new_agent_id,
        status="active",
        created_at=now,
        last_update=now,
        parent_agent_id=parent_agent_id,
        spawn_reason=spawn_reason,
        tags=["spawned", f"parent:{parent_agent_id}"],
        notes=f"Spawned from '{parent_agent_id}' ({spawn_reason}). Inherited {inheritance_factor*100:.0f}% of thermodynamic state."
    )
    new_meta.add_lifecycle_event("spawned", f"From {parent_agent_id}: {spawn_reason}")
    
    agent_metadata[new_agent_id] = new_meta
    monitors[new_agent_id] = new_monitor
    
    # Save metadata
    save_metadata()
    
    print(f"[UNITARES MCP] Spawned agent '{new_agent_id}' from '{parent_agent_id}' (inheritance: {inheritance_factor*100:.0f}%)", file=sys.stderr)
    
    return new_monitor


def get_or_create_monitor(agent_id: str) -> UNITARESMonitor:
    """Get existing monitor or create new one with metadata, loading state if it exists"""
    # Ensure metadata exists
    get_or_create_metadata(agent_id)

    # Create monitor if needed
    if agent_id not in monitors:
        monitor = UNITARESMonitor(agent_id)
        
        # Try to load persisted state from disk
        persisted_state = load_monitor_state(agent_id)
        if persisted_state is not None:
            monitor.state = persisted_state
            print(f"[UNITARES MCP] Loaded persisted state for {agent_id} ({len(persisted_state.V_history)} history entries)", file=sys.stderr)
        else:
            print(f"[UNITARES MCP] Initialized new monitor for {agent_id}", file=sys.stderr)
        
        monitors[agent_id] = monitor
    
    return monitors[agent_id]


def check_agent_status(agent_id: str) -> str | None:
    """Check if agent status allows operations, return error if not"""
    if agent_id in agent_metadata:
        meta = agent_metadata[agent_id]
        if meta.status == "paused":
            return f"Agent '{agent_id}' is paused. Resume it first before processing updates."
        elif meta.status == "archived":
            return f"Agent '{agent_id}' is archived. It must be restored before processing updates."
        elif meta.status == "deleted":
            return f"Agent '{agent_id}' is deleted and cannot be used."
    return None


def check_agent_id_default(agent_id: str) -> str | None:
    """Check if using default agent_id and return warning if so"""
    if not agent_id or agent_id == "default_agent":
        return "⚠️ Using default agent_id. For multi-agent systems, specify explicit agent_id to avoid state mixing."
    return None


def check_spawn_warning(agent_id: str) -> tuple[bool, str]:
    """
    Check if spawning might be inappropriate (e.g., similar active agent exists).
    
    Returns:
        (should_warn, warning_message)
    """
    # Check for similar active agents (same prefix/base)
    base_parts = agent_id.split("_")[:2]  # First 2 parts (e.g., "claude_code" from "claude_code_cli_session")
    if len(base_parts) >= 2:
        base_pattern = "_".join(base_parts)
        similar_agents = [
            aid for aid, meta in agent_metadata.items()
            if aid.startswith(base_pattern) and meta.status == "active" and aid != agent_id
        ]
        
        if similar_agents:
            return True, f"Found similar active agent(s): {', '.join(similar_agents[:3])}. Consider self-updating instead of spawning to maintain identity and accountability."
    
    return False, ""


def _detect_ci_status() -> bool:
    """
    Auto-detect CI pass status from environment variables.
    
    Checks common CI environment variables:
    - CI=true + CI_STATUS=passed (custom)
    - GITHUB_ACTIONS + GITHUB_WORKFLOW_STATUS=success (GitHub Actions)
    - TRAVIS=true + TRAVIS_TEST_RESULT=0 (Travis CI)
    - CIRCLE_CI=true + CIRCLE_BUILD_STATUS=success (CircleCI)
    - GITLAB_CI=true + CI_JOB_STATUS=success (GitLab CI)
    
    Returns:
        bool: True if CI passed, False otherwise (conservative default)
    """
    # Check if we're in a CI environment
    ci_env = os.environ.get("CI", "").lower()
    if ci_env not in ("true", "1", "yes"):
        return False  # Not in CI, default to False (conservative)
    
    # Check custom CI_STATUS
    ci_status = os.environ.get("CI_STATUS", "").lower()
    if ci_status in ("passed", "success", "ok", "true", "1"):
        return True
    
    # GitHub Actions
    if os.environ.get("GITHUB_ACTIONS") == "true":
        workflow_status = os.environ.get("GITHUB_WORKFLOW_STATUS", "").lower()
        if workflow_status == "success":
            return True
    
    # Travis CI
    if os.environ.get("TRAVIS") == "true":
        test_result = os.environ.get("TRAVIS_TEST_RESULT", "")
        if test_result == "0":
            return True
    
    # CircleCI
    if os.environ.get("CIRCLE_CI") == "true":
        build_status = os.environ.get("CIRCLE_BUILD_STATUS", "").lower()
        if build_status == "success":
            return True
    
    # GitLab CI
    if os.environ.get("GITLAB_CI") == "true":
        job_status = os.environ.get("CI_JOB_STATUS", "").lower()
        if job_status == "success":
            return True
    
    # Default: CI detected but status unknown -> False (conservative)
    return False


def validate_agent_id_format(agent_id: str) -> tuple[bool, str, str]:
    """
    Validate agent_id follows recommended patterns.
    
    Returns:
        (is_valid, error_message, suggestion)
    """
    from datetime import datetime, timedelta
    import re
    
    # Generic IDs that should be rejected
    generic_ids = {
        "test", "demo", "default_agent", "agent", "monitor"
    }
    
    if agent_id.lower() in generic_ids:
        suggestion = f"{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Generic ID '{agent_id}' is not allowed. Use a specific identifier.", suggestion
    
    # Check for generic patterns without uniqueness
    if agent_id in ["claude_code_cli", "claude_chat", "composer", "cursor_ide"]:
        suggestion = f"{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"ID '{agent_id}' is too generic and may cause collisions. Add a session identifier.", suggestion
    
    # Test agents should include timestamp
    if agent_id.startswith("test_") and len(agent_id.split("_")) < 3:
        suggestion = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Test IDs should include timestamp for uniqueness (e.g., 'test_20251124_143022').", suggestion
    
    # Demo agents should include timestamp
    if agent_id.startswith("demo_") and len(agent_id.split("_")) < 3:
        suggestion = f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return False, f"Demo IDs should include timestamp for uniqueness (e.g., 'demo_20251124_143022').", suggestion
    
    # Check length (too short might be generic)
    if len(agent_id) < 3:
        return False, f"Agent ID '{agent_id}' is too short. Use at least 3 characters.", ""
    
    # Check for invalid characters (allow alphanumeric, underscore, hyphen)
    if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
        return False, f"Agent ID '{agent_id}' contains invalid characters. Use only letters, numbers, underscores, and hyphens.", ""
    
    return True, "", ""


def require_agent_id(arguments: dict, reject_existing: bool = False) -> tuple[str | None, TextContent | None]:
    """
    Require explicit agent_id, validate format, return error if missing or invalid.
    
    Args:
        arguments: Tool arguments dict containing 'agent_id'
        reject_existing: If True, reject agent_ids that already exist (for new agent creation).
                        If False, allow existing agent_ids (for updates).
    
    Returns:
        (agent_id, None) if valid, (None, TextContent error) if invalid
    """
    agent_id = arguments.get("agent_id")
    if not agent_id:
        error_msg = json.dumps({
            "success": False,
            "error": "agent_id is required. Each agent must have a UNIQUE identifier to prevent state mixing.",
            "details": "Use a unique session/purpose identifier (e.g., 'cursor_ide_session_001', 'claude_code_cli_20251124', 'debugging_session_20251124').",
            "why_unique": "Each agent_id is a unique identity. Using another agent's ID is identity theft - you would impersonate them, corrupt their history, and erase their governance record.",
            "examples": [
                "cursor_ide_session_001",
                "claude_code_cli_20251124",
                "debugging_session_20251124",
                "production_agent_v2"
            ],
            "suggestion": "\"agent_id\": \"your_unique_session_id\""
        }, indent=2)
        return None, TextContent(type="text", text=error_msg)
    
    # Check if agent_id already exists (identity collision) - only when creating new agents
    if reject_existing and agent_id in agent_metadata:
        existing_meta = agent_metadata[agent_id]
        from datetime import datetime, timedelta
        try:
            created_dt = datetime.fromisoformat(existing_meta.created_at.replace('Z', '+00:00') if 'Z' in existing_meta.created_at else existing_meta.created_at)
            created_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            created_str = existing_meta.created_at
        
        error_msg = json.dumps({
            "success": False,
            "error": "Identity collision: This agent_id already exists",
            "details": f"'{agent_id}' is an existing agent identity (created {created_str}, {existing_meta.total_updates} updates)",
            "why_this_matters": "Using another agent's ID is identity theft. You would impersonate them and corrupt their governance history.",
            "suggestion": f"Create a unique agent_id for yourself (e.g., 'your_name_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}')",
            "help": "Use list_agents to see existing agent IDs and avoid collisions"
        }, indent=2)
        return None, TextContent(type="text", text=error_msg)
    
    # Validate format (but allow existing agents to pass - backward compatibility)
    # Only validate for new agents (not in metadata yet)
    if agent_id not in agent_metadata:
        is_valid, error_message, suggestion = validate_agent_id_format(agent_id)
        if not is_valid:
            error_data = {
                "success": False,
                "error": error_message,
                "agent_id_provided": agent_id
            }
            if suggestion:
                error_data["suggestion"] = f"Try: '{suggestion}'"
                error_data["example"] = f"Or use a more descriptive ID like: '{agent_id}_session_001'"
            
            error_msg = json.dumps(error_data, indent=2)
            return None, TextContent(type="text", text=error_msg)
    
    return agent_id, None


def generate_api_key() -> str:
    """
    Generate a secure 32-byte API key for agent authentication.
    
    Returns:
        Base64-encoded API key string (URL-safe, no padding)
    """
    key_bytes = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key_bytes).decode('ascii').rstrip('=')


def verify_agent_ownership(agent_id: str, api_key: str) -> tuple[bool, str | None]:
    """
    Verify that the caller owns the agent_id by checking API key.
    
    Args:
        agent_id: Agent ID to verify
        api_key: API key provided by caller
    
    Returns:
        (is_valid, error_message)
        - is_valid=True if key matches, False otherwise
        - error_message=None if valid, error description if invalid
    """
    if agent_id not in agent_metadata:
        return False, f"Agent '{agent_id}' does not exist"
    
    meta = agent_metadata[agent_id]
    stored_key = meta.api_key
    
    # Handle backward compatibility: if no API key stored, allow (with warning)
    if stored_key is None:
        # Lazy migration: generate key for existing agent
        stored_key = generate_api_key()
        meta.api_key = stored_key
        # Note: We don't save here - caller should save metadata after update
        # This allows first update to work, but subsequent updates require the key
        return True, None
    
    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, stored_key):
        return False, "Invalid API key. This agent_id belongs to another identity."
    
    return True, None


def require_agent_auth(agent_id: str, arguments: dict, enforce: bool = False) -> tuple[bool, TextContent | None]:
    """
    Require and verify API key for agent authentication.
    
    Args:
        agent_id: Agent ID being accessed
        arguments: Tool arguments dict (should contain 'api_key')
        enforce: If True, require API key even for agents without one (new behavior)
                 If False, allow missing key for backward compatibility (migration mode)
    
    Returns:
        (is_valid, error) - is_valid=True if authenticated, False if error
    """
    api_key = arguments.get("api_key")
    
    # Check if agent exists
    if agent_id not in agent_metadata:
        # New agent - will get key on creation
        return True, None
    
    meta = agent_metadata[agent_id]
    
    # If agent has no API key yet (backward compatibility)
    if meta.api_key is None:
        if enforce:
            # New behavior: require key even for existing agents
            return False, TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "API key required for authentication",
                    "details": f"Agent '{agent_id}' requires an API key for updates. This is a security requirement to prevent impersonation.",
                    "migration": "This agent was created before authentication was added. Generate a key using get_agent_api_key tool.",
                    "suggestion": "Use get_agent_api_key tool to retrieve or generate your API key"
                }, indent=2)
            )
        else:
            # Migration mode: allow first update, generate key
            return True, None
    
    # Agent has API key - require it
    if not api_key:
        return False, TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "API key required",
                "details": f"Agent '{agent_id}' requires an API key for authentication. This prevents impersonation and protects your identity.",
                "why_this_matters": "Without authentication, anyone could update your agent's state, corrupt your history, and manipulate your governance record.",
                "suggestion": "Include 'api_key' parameter in your request. Use get_agent_api_key tool to retrieve your key."
            }, indent=2)
        )
    
    # Verify key
    is_valid, error_msg = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        return False, TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Authentication failed",
                "details": error_msg or "Invalid API key",
                "why_this_matters": "This agent_id belongs to another identity. Using it would be identity theft.",
                "suggestion": "Use your own agent_id and API key, or create a new agent_id for yourself"
            }, indent=2)
        )
    
    return True, None


def process_update_authenticated(
    agent_id: str,
    api_key: str,
    agent_state: dict,
    auto_save: bool = True
) -> dict:
    """
    Process governance update with authentication enforcement (synchronous version).

    This is the SECURE entry point for processing updates. Use this instead of
    calling UNITARESMonitor.process_update() directly to prevent impersonation.

    Args:
        agent_id: Agent identifier
        api_key: API key for authentication
        agent_state: Agent state dict (parameters, ethical_drift, etc.)
        auto_save: If True, automatically save state to disk after update

    Returns:
        Update result dict with metrics and decision

    Raises:
        PermissionError: If authentication fails
        ValueError: If agent_id is invalid
    """
    # Authenticate ownership
    is_valid, error_msg = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        raise PermissionError(f"Authentication failed: {error_msg}")

    # Get or create monitor
    monitor = get_or_create_monitor(agent_id)

    # Process update (now authenticated)
    result = monitor.process_update(agent_state)

    # Auto-save state if requested
    if auto_save:
        save_monitor_state(agent_id, monitor)

        # Update metadata
        meta = agent_metadata[agent_id]
        meta.last_update = datetime.now().isoformat()
        meta.total_updates += 1
        save_metadata()

    return result


def detect_loop_pattern(agent_id: str) -> tuple[bool, str]:
    """
    Detect recursive self-monitoring loop patterns.
    
    Detects patterns like:
    - 3+ updates within 10 seconds
    - Multiple "reject" decisions in rapid succession
    - Updates happening faster than reasonable (same second)
    
    Returns:
        (is_loop, reason) - True if loop detected, with explanation
    """
    if agent_id not in agent_metadata:
        return False, ""
    
    meta = agent_metadata[agent_id]
    
    # Check cooldown period
    if meta.loop_cooldown_until:
        cooldown_until = datetime.fromisoformat(meta.loop_cooldown_until)
        if datetime.now() < cooldown_until:
            remaining = (cooldown_until - datetime.now()).total_seconds()
            return True, f"Loop cooldown active. Wait {remaining:.1f}s before retrying."
    
    # Need at least 3 recent updates to detect pattern
    if len(meta.recent_update_timestamps) < 3:
        return False, ""
    
    # Get last 5 updates (or all if fewer)
    recent_timestamps = meta.recent_update_timestamps[-5:]
    recent_decisions = meta.recent_decisions[-5:]
    
    # Pattern 1: Multiple updates within same second
    if len(recent_timestamps) >= 2:
        last_two = recent_timestamps[-2:]
        try:
            t1 = datetime.fromisoformat(last_two[0])
            t2 = datetime.fromisoformat(last_two[1])
            if (t2 - t1).total_seconds() < 1.0:
                return True, "Rapid-fire updates detected (multiple updates within 1 second)"
        except (ValueError, TypeError):
            pass
    
    # Pattern 2: 3+ updates within 10 seconds, all with "reject" decisions
    if len(recent_timestamps) >= 3:
        last_three_timestamps = recent_timestamps[-3:]
        last_three_decisions = recent_decisions[-3:]
        
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_three_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()
            
            if time_span <= 10.0:  # Within 10 seconds
                reject_count = sum(1 for d in last_three_decisions if d == "reject")
                if reject_count >= 2:  # At least 2 rejects
                    return True, f"Recursive reject pattern: {reject_count} reject decisions within {time_span:.1f}s"
        except (ValueError, TypeError):
            pass
    
    # Pattern 3: 4+ updates within 5 seconds (any decisions)
    if len(recent_timestamps) >= 4:
        last_four_timestamps = recent_timestamps[-4:]
        try:
            timestamps = [datetime.fromisoformat(ts) for ts in last_four_timestamps]
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()
            
            if time_span <= 5.0:  # Within 5 seconds
                return True, f"Rapid update pattern: 4+ updates within {time_span:.1f}s"
        except (ValueError, TypeError):
            pass
    
    return False, ""


async def process_update_authenticated_async(
    agent_id: str,
    api_key: str,
    agent_state: dict,
    auto_save: bool = True,
    confidence: float = 1.0
) -> dict:
    """
    Process governance update with authentication enforcement (async version).

    This is the SECURE async entry point for processing updates. Use this in async
    contexts (like MCP handlers) instead of calling UNITARESMonitor.process_update()
    directly to prevent impersonation.

    Args:
        agent_id: Agent identifier
        api_key: API key for authentication
        agent_state: Agent state dict (parameters, ethical_drift, etc.)
        auto_save: If True, automatically save state to disk after update (async)
        confidence: Confidence level [0, 1] for this update. Defaults to 1.0.
                    When confidence < 0.8, lambda1 updates are skipped.

    Returns:
        Update result dict with metrics and decision

    Raises:
        PermissionError: If authentication fails
        ValueError: If agent_id is invalid
    """
    # Authenticate ownership
    is_valid, error_msg = verify_agent_ownership(agent_id, api_key)
    if not is_valid:
        raise PermissionError(f"Authentication failed: {error_msg}")

    # Check for loop pattern BEFORE processing
    is_loop, loop_reason = detect_loop_pattern(agent_id)
    if is_loop:
        # Set cooldown period (30 seconds)
        meta = agent_metadata[agent_id]
        cooldown_until = datetime.now() + timedelta(seconds=30)
        meta.loop_cooldown_until = cooldown_until.isoformat()
        if not meta.loop_detected_at:
            meta.loop_detected_at = datetime.now().isoformat()
            meta.add_lifecycle_event("loop_detected", loop_reason)
            print(f"[UNITARES MCP] ⚠️  Loop detected for agent '{agent_id}': {loop_reason}", file=sys.stderr)
        
        await save_metadata_async()
        
        raise ValueError(
            f"Self-monitoring loop detected: {loop_reason}. "
            f"Updates blocked for 30 seconds to prevent system crash. "
            f"Cooldown until: {cooldown_until.isoformat()}"
        )

    # Get or create monitor
    monitor = get_or_create_monitor(agent_id)

    # Process update (now authenticated) with confidence gating
    result = monitor.process_update(agent_state, confidence=confidence)

    # Auto-save state if requested (async)
    if auto_save:
        await save_monitor_state_async(agent_id, monitor)

        # Update metadata
        meta = agent_metadata[agent_id]
        now = datetime.now().isoformat()
        meta.last_update = now
        meta.total_updates += 1
        
        # Track recent updates for loop detection (keep last 10)
        decision_action = result.get('decision', {}).get('action', 'unknown')
        meta.recent_update_timestamps.append(now)
        meta.recent_decisions.append(decision_action)
        
        # Keep only last 10 entries
        if len(meta.recent_update_timestamps) > 10:
            meta.recent_update_timestamps = meta.recent_update_timestamps[-10:]
            meta.recent_decisions = meta.recent_decisions[-10:]
        
        # Clear cooldown if it has passed
        if meta.loop_cooldown_until:
            cooldown_until = datetime.fromisoformat(meta.loop_cooldown_until)
            if datetime.now() >= cooldown_until:
                meta.loop_cooldown_until = None
        
        await save_metadata_async()

    return result


def get_agent_or_error(agent_id: str) -> tuple[UNITARESMonitor | None, str | None]:
    """Get agent with friendly error message if not found"""
    if agent_id not in monitors:
        available = list(monitors.keys())
        if available:
            error = f"Agent '{agent_id}' not found. Available agents: {available}. Call process_agent_update first to initialize."
        else:
            error = f"Agent '{agent_id}' not found. No agents initialized yet. Call process_agent_update first."
        return None, error
    return monitors[agent_id], None


def build_standardized_agent_info(
    agent_id: str,
    meta: AgentMetadata,
    monitor: UNITARESMonitor | None = None,
    include_metrics: bool = True
) -> dict:
    """
    Build standardized agent info structure.
    Always returns same fields, null if unavailable.
    """
    # Determine timestamps (prefer monitor, fallback to metadata)
    if monitor:
        # Use monitor timestamps if available, fallback to metadata
        if hasattr(monitor, 'created_at') and monitor.created_at:
            created_ts = monitor.created_at.isoformat()
        else:
            created_ts = meta.created_at
        
        if hasattr(monitor, 'last_update') and monitor.last_update:
            last_update_ts = monitor.last_update.isoformat()
        else:
            last_update_ts = meta.last_update
        
        update_count = int(monitor.state.update_count)
    else:
        created_ts = meta.created_at
        last_update_ts = meta.last_update
        update_count = meta.total_updates
    
    # Calculate age in days
    try:
        created_dt = datetime.fromisoformat(created_ts.replace('Z', '+00:00') if 'Z' in created_ts else created_ts)
        age_days = (datetime.now(created_dt.tzinfo) - created_dt).days
    except:
        age_days = None
    
    # Extract primary tags (first 3, or all if <= 3)
    primary_tags = (meta.tags or [])[:3] if meta.tags else []
    
    # Notes preview (first 100 chars)
    notes_preview = None
    if meta.notes:
        notes_preview = meta.notes[:100] + "..." if len(meta.notes) > 100 else meta.notes
    
    # Build summary
    summary = {
        "updates": update_count,
        "last_activity": last_update_ts,
        "age_days": age_days,
        "primary_tags": primary_tags
    }
    
    # Build metrics (null if unavailable)
    metrics = None
    health_status = "unknown"
    state_info = {
        "loaded_in_process": monitor is not None,
        "metrics_available": False,
        "error": None
    }
    
    if monitor and include_metrics:
        try:
            monitor_state = monitor.state
            risk_score = getattr(monitor_state, 'risk_score', None)
            health_status_obj, _ = health_checker.get_health_status(
                risk_score=risk_score,
                coherence=monitor_state.coherence,
                void_active=monitor_state.void_active
            )
            health_status = health_status_obj.value
            
            metrics = {
                "risk_score": float(risk_score) if risk_score is not None else None,
                "coherence": float(monitor_state.coherence),
                "void_active": bool(monitor_state.void_active),
                "E": float(monitor_state.E),
                "I": float(monitor_state.I),
                "S": float(monitor_state.S),
                "V": float(monitor_state.V),
                "lambda1": float(monitor_state.lambda1)
            }
            state_info["metrics_available"] = True
        except Exception as e:
            health_status = "error"
            state_info["error"] = str(e)
            state_info["metrics_available"] = False
    
    # Build spawn relationship info
    spawn_info = None
    if meta.parent_agent_id:
        spawn_info = {
            "parent_agent_id": meta.parent_agent_id,
            "spawn_reason": meta.spawn_reason or "spawned",
            "is_spawned": True
        }
        # Check if parent still exists
        if meta.parent_agent_id in agent_metadata:
            parent_meta = agent_metadata[meta.parent_agent_id]
            spawn_info["parent_status"] = parent_meta.status
        else:
            spawn_info["parent_status"] = "deleted"
    
    # Build standardized structure
    return {
        "agent_id": agent_id,
        "lifecycle_status": meta.status,
        "health_status": health_status,
        "summary": summary,
        "metrics": metrics,
        "metadata": {
            "created": created_ts,
            "last_update": last_update_ts,
            "version": meta.version,
            "total_updates": meta.total_updates,
            "tags": meta.tags or [],
            "notes_preview": notes_preview,
            "spawn_info": spawn_info
        },
        "state": state_info
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools"""
    return [
        Tool(
            name="check_calibration",
            description="Check calibration of confidence estimates. Returns whether confidence estimates match actual accuracy. Requires ground truth data via update_calibration_ground_truth.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="update_calibration_ground_truth",
            description="Update calibration with ground truth after human review. This allows calibration to work properly by updating actual correctness after decisions are made.",
            inputSchema={
                "type": "object",
                "properties": {
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level (0-1) for the prediction",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "predicted_correct": {
                        "type": "boolean",
                        "description": "Whether we predicted correct (based on confidence threshold)"
                    },
                    "actual_correct": {
                        "type": "boolean",
                        "description": "Whether prediction was actually correct (ground truth from human review)"
                    }
                },
                "required": ["confidence", "predicted_correct", "actual_correct"]
            }
        ),
        Tool(
            name="health_check",
            description="Quick health check - returns system status, version, and component health. Useful for monitoring and operational visibility.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="get_telemetry_metrics",
            description="Get comprehensive telemetry metrics: skip rates, confidence distributions, calibration status, and suspicious patterns. Useful for monitoring system health and detecting agreeableness or over-conservatism.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Optional agent ID to filter metrics. If not provided, returns metrics for all agents."
                    },
                    "window_hours": {
                        "type": "number",
                        "description": "Time window in hours for metrics (default: 24)",
                        "default": 24
                    }
                }
            }
        ),
        Tool(
            name="store_knowledge",
            description="Store knowledge (discovery, pattern, lesson, or question) for an agent. Enables structured learning beyond thermodynamic metrics. Knowledge persists across sessions. PREFERRED over creating markdown files - use this for most discoveries/insights. Only create markdown files for comprehensive reports (1000+ words).",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "knowledge_type": {
                        "type": "string",
                        "enum": ["discovery", "pattern", "lesson", "question"],
                        "description": "Type of knowledge to store"
                    },
                    "discovery_type": {
                        "type": "string",
                        "enum": ["bug_found", "insight", "pattern", "improvement", "question"],
                        "description": "Required if knowledge_type='discovery'. Type of discovery."
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-line summary (required for discovery/pattern)"
                    },
                    "details": {
                        "type": "string",
                        "description": "Full details/explanation (optional)"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Severity level (optional, for discovery/pattern)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization (optional)"
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Related file paths (optional, for discovery)"
                    },
                    "pattern_id": {
                        "type": "string",
                        "description": "Required if knowledge_type='pattern'. Unique pattern identifier."
                    },
                    "description": {
                        "type": "string",
                        "description": "Required if knowledge_type='pattern'. Pattern description."
                    },
                    "lesson": {
                        "type": "string",
                        "description": "Required if knowledge_type='lesson'. Lesson learned."
                    },
                    "question": {
                        "type": "string",
                        "description": "Required if knowledge_type='question'. Question raised."
                    }
                },
                "required": ["agent_id", "knowledge_type"]
            }
        ),
        Tool(
            name="retrieve_knowledge",
            description="Retrieve an agent's complete knowledge record (discoveries, patterns, lessons, questions).",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="search_knowledge",
            description="Search knowledge across agents with filters, full-text search, and sorting. Enables cross-agent learning and pattern discovery.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Optional: Filter by specific agent. If not provided, searches all agents."
                    },
                    "discovery_type": {
                        "type": "string",
                        "enum": ["bug_found", "insight", "pattern", "improvement", "question"],
                        "description": "Optional: Filter by discovery type"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: Filter by tags (returns discoveries matching any tag)"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Optional: Filter by severity"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived"],
                        "description": "Optional: Filter by status"
                    },
                    "search_text": {
                        "type": "string",
                        "description": "Optional: Full-text search in summary and details (case-insensitive)"
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["timestamp", "severity", "status"],
                        "description": "Sort field (default: timestamp)",
                        "default": "timestamp"
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": ["asc", "desc"],
                        "description": "Sort direction (default: desc)",
                        "default": "desc"
                    }
                }
            }
        ),
        Tool(
            name="list_knowledge",
            description="List all stored knowledge entries across agents. Returns summary statistics and available knowledge.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="update_discovery_status",
            description="Update the status of a discovery (open, resolved, archived). Enables lifecycle management for discoveries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "discovery_timestamp": {
                        "type": "string",
                        "description": "Timestamp of the discovery to update (ISO format)"
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived"],
                        "description": "New status for the discovery"
                    },
                    "resolved_reason": {
                        "type": "string",
                        "description": "Optional reason/note for resolution (appended to details)"
                    }
                },
                "required": ["agent_id", "discovery_timestamp", "new_status"]
            }
        ),
        Tool(
            name="update_discovery",
            description="Update fields of a discovery (summary, details, severity, tags, status, related_files). Enables discovery editing and corrections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "discovery_timestamp": {
                        "type": "string",
                        "description": "Timestamp of the discovery to update (ISO format)"
                    },
                    "summary": {
                        "type": "string",
                        "description": "New summary (replaces existing)"
                    },
                    "details": {
                        "type": "string",
                        "description": "New details (replaces existing unless append_details=True)"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "New severity level"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags list (replaces existing)"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "resolved", "archived"],
                        "description": "New status"
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New related files list (replaces existing)"
                    },
                    "append_details": {
                        "type": "boolean",
                        "description": "If true, append to details instead of replacing",
                        "default": False
                    }
                },
                "required": ["agent_id", "discovery_timestamp"]
            }
        ),
        Tool(
            name="find_similar_discoveries",
            description="Find discoveries with similar summaries using text similarity. Helps identify duplicates and related discoveries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary text to compare against"
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Similarity threshold (0.0-1.0), higher = more strict",
                        "default": 0.7,
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Optional: Filter by specific agent"
                    }
                },
                "required": ["summary"]
            }
        ),
        Tool(
            name="get_server_info",
            description="Get MCP server version, process information, and health status for debugging multi-process issues. Returns version, PID, uptime, and active process count.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="process_agent_update",
            description="Run one complete governance cycle for an agent. Processes agent state and returns governance decision, metrics, and sampling parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE identifier for the agent. Must be unique across all agents to prevent state mixing. Examples: 'cursor_ide_session_001', 'claude_code_cli_20251124', 'debugging_session_20251124'. Avoid generic IDs like 'test' or 'demo'."
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Agent parameters vector (128 dimensions). First 6 are core metrics: [length_score, complexity, info_score, coherence_score, placeholder, ethical_drift]",
                        "default": []
                    },
                    "ethical_drift": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Ethical drift signals (3 components): [primary_drift, coherence_loss, complexity_contribution]",
                        "default": [0.0, 0.0, 0.0]
                    },
                    "response_text": {
                        "type": "string",
                        "description": "Agent's response text (optional, for analysis)"
                    },
                    "complexity": {
                        "type": "number",
                        "description": "Estimated task complexity (0-1, optional)",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level for this update (0-1, optional). When confidence < 0.8, lambda1 updates are skipped. Defaults to 1.0 (fully confident).",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 1.0
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication. Required to prove ownership of agent_id. Prevents impersonation and identity theft. Use get_agent_api_key tool to retrieve your key."
                    },
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_governance_metrics",
            description="Get current governance state and metrics for an agent. Returns E, I, S, V, coherence, λ₁, risk score, and sampling parameters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE agent identifier. Must match an existing agent ID."
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_system_history",
            description="Export complete governance history for an agent. Returns time series data of all governance metrics directly in the response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "UNIQUE agent identifier. Must match an existing agent ID."
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format",
                        "default": "json"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="export_to_file",
            description="Export governance history to a file in the server's data directory. Saves timestamped files for analysis and archival. Returns file path and metadata (lightweight response).",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "csv"],
                        "description": "Output format (json or csv)",
                        "default": "json"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename (without extension). If not provided, uses agent_id with timestamp."
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="reset_monitor",
            description="Reset governance state for an agent. Useful for testing or starting fresh.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="list_agents",
            description="List all agents currently being monitored with lifecycle metadata and health status. Returns standardized format with consistent structure for all agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary_only": {
                        "type": "boolean",
                        "description": "Return only summary statistics (counts), no agent details",
                        "default": False
                    },
                    "status_filter": {
                        "type": "string",
                        "enum": ["active", "paused", "archived", "deleted", "all"],
                        "description": "Filter agents by lifecycle status",
                        "default": "all"
                    },
                    "loaded_only": {
                        "type": "boolean",
                        "description": "Only show agents with monitors loaded in this process",
                        "default": False
                    },
                    "include_metrics": {
                        "type": "boolean",
                        "description": "Include full EISV metrics for loaded agents (faster if False)",
                        "default": True
                    },
                    "grouped": {
                        "type": "boolean",
                        "description": "Group agents by status (active/paused/archived/deleted) for easier scanning",
                        "default": True
                    },
                    "standardized": {
                        "type": "boolean",
                        "description": "Use standardized format with consistent fields (all fields always present, null if unavailable)",
                        "default": True
                    }
                }
            }
        ),
        Tool(
            name="delete_agent",
            description="Delete an agent and archive its data. Protected: cannot delete pioneer agents. Requires explicit confirmation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to delete"
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                        "default": False
                    },
                    "backup_first": {
                        "type": "boolean",
                        "description": "Archive data before deletion",
                        "default": True
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_agent_metadata",
            description="Get complete metadata for an agent including lifecycle events, current state, and computed fields.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="archive_agent",
            description="Archive an agent for long-term storage. Agent can be resumed later. Optionally unload from memory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to archive"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for archiving (optional)"
                    },
                    "keep_in_memory": {
                        "type": "boolean",
                        "description": "Keep agent loaded in memory",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="update_agent_metadata",
            description="Update agent tags and notes. Tags are replaced, notes can be appended or replaced.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New tags (replaces existing)"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Notes to add or replace"
                    },
                    "append_notes": {
                        "type": "boolean",
                        "description": "Append notes with timestamp instead of replacing",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="archive_old_test_agents",
            description="Manually archive old test/demo agents that haven't been updated recently. Note: This also runs automatically on server startup with a 7-day threshold. Use this tool to trigger with a custom threshold or on-demand.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_age_days": {
                        "type": "number",
                        "description": "Archive test agents older than this many days",
                        "default": 7,
                        "minimum": 1
                    }
                }
            }
        ),
        Tool(
            name="simulate_update",
            description="Dry-run governance cycle. Returns decision without persisting state. Useful for testing decisions before committing. State is NOT modified.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Agent parameters vector (128 dimensions)",
                        "default": []
                    },
                    "ethical_drift": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Ethical drift signals (3 components)",
                        "default": [0.0, 0.0, 0.0]
                    },
                    "response_text": {
                        "type": "string",
                        "description": "Agent's response text (optional)"
                    },
                    "complexity": {
                        "type": "number",
                        "description": "Estimated task complexity (0-1)",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.5
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence level for this update (0-1, optional). When confidence < 0.8, lambda1 updates are skipped. Defaults to 1.0.",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 1.0
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key for authentication"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_thresholds",
            description="Get current governance threshold configuration. Returns runtime overrides + defaults. Enables agents to understand decision boundaries.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="set_thresholds",
            description="Set runtime threshold overrides. Enables runtime adaptation without redeploy. Validates values and returns success/errors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thresholds": {
                        "type": "object",
                        "description": "Dict of threshold_name -> value. Valid keys: risk_approve_threshold, risk_revise_threshold, coherence_critical_threshold, void_threshold_initial",
                        "additionalProperties": {"type": "number"}
                    },
                    "validate": {
                        "type": "boolean",
                        "description": "Validate values are in reasonable ranges",
                        "default": True
                    }
                },
                "required": ["thresholds"]
            }
        ),
        Tool(
            name="aggregate_metrics",
            description="Get fleet-level health overview. Aggregates metrics across all agents or a subset. Returns summary statistics for coordination and system management.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to aggregate (null/empty = all agents)"
                    },
                    "include_health_breakdown": {
                        "type": "boolean",
                        "description": "Include health status breakdown",
                        "default": True
                    }
                }
            }
        ),
        Tool(
            name="observe_agent",
            description="Observe another agent's governance state with pattern analysis. Combines metrics, history, and analysis into a single call optimized for AI agents. Returns current state, trends, anomalies, and summary statistics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to observe"
                    },
                    "include_history": {
                        "type": "boolean",
                        "description": "Include recent history (last 10 updates)",
                        "default": True
                    },
                    "analyze_patterns": {
                        "type": "boolean",
                        "description": "Perform pattern analysis (trends, anomalies)",
                        "default": True
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="compare_agents",
            description="Compare governance patterns across multiple agents. Returns similarities, differences, and outliers. Optimized for AI agent consumption.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of agent IDs to compare (2-10 agents recommended)"
                    },
                    "compare_metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Metrics to compare (default: all)",
                        "default": ["risk_score", "coherence", "E", "I", "S"]
                    }
                },
                "required": ["agent_ids"]
            }
        ),
        Tool(
            name="detect_anomalies",
            description="Detect anomalies across agents. Scans all agents or a subset for unusual patterns (risk spikes, coherence drops, void events). Returns prioritized anomalies with severity levels.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to scan (null/empty = all agents)"
                    },
                    "anomaly_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Types of anomalies to detect",
                        "default": ["risk_spike", "coherence_drop"]
                    },
                    "min_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Minimum severity to report",
                        "default": "medium"
                    }
                }
            }
        ),
        Tool(
            name="get_agent_api_key",
            description="Get or generate API key for an agent. Required for authentication when updating agent state. Prevents impersonation and identity theft.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier"
                    },
                    "regenerate": {
                        "type": "boolean",
                        "description": "Regenerate API key (invalidates old key)",
                        "default": False
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="list_tools",
            description="List all available governance tools with descriptions and categories. Provides runtime introspection for agents to discover capabilities. Useful for onboarding new agents and understanding the toolset.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="cleanup_stale_locks",
            description="Clean up stale lock files that are no longer held by active processes. Prevents lock accumulation from crashed/killed processes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_age_seconds": {
                        "type": "number",
                        "description": "Maximum age in seconds before considering stale (default: 300 = 5 minutes)",
                        "default": 300.0
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If True, only report what would be cleaned (default: False)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="request_dialectic_review",
            description="Request a dialectic review for a paused/critical agent. Selects a healthy reviewer agent and initiates dialectic session for circuit breaker recovery.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of paused agent requesting review"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for circuit breaker trigger",
                        "default": "Circuit breaker triggered"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key for authentication"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="submit_thesis",
            description="Paused agent submits thesis: 'What I did, what I think happened'. First step in dialectic recovery process.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Paused agent ID"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key"
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "Agent's understanding of what caused the issue"
                    },
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of conditions for resumption"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Natural language explanation"
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="submit_antithesis",
            description="Reviewer agent submits antithesis: 'What I observe, my concerns'. Second step in dialectic recovery process.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Reviewer agent ID"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Reviewer's API key"
                    },
                    "observed_metrics": {
                        "type": "object",
                        "description": "Metrics observed about paused agent",
                        "additionalProperties": True
                    },
                    "concerns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of concerns"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Natural language explanation"
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="submit_synthesis",
            description="Either agent submits synthesis proposal during negotiation. Multiple rounds until convergence. Third step in dialectic recovery process.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (either paused or reviewer)"
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Agent's API key"
                    },
                    "proposed_conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Proposed resumption conditions"
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "Agreed understanding of root cause"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explanation of proposal"
                    },
                    "agrees": {
                        "type": "boolean",
                        "description": "Whether this agent agrees with current proposal",
                        "default": False
                    }
                },
                "required": ["session_id", "agent_id"]
            }
        ),
        Tool(
            name="get_dialectic_session",
            description="Get current state of a dialectic session. Returns full session state including transcript, phase, and resolution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Dialectic session ID"
                    }
                },
                "required": ["session_id"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> Sequence[TextContent]:
    """Handle tool calls from MCP client"""
    if arguments is None:
        arguments = {}
    
    # All handlers are now in the registry - dispatch to handler
    try:
        from src.mcp_handlers import dispatch_tool
        result = await dispatch_tool(name, arguments)
        if result is not None:
            return result
        # If None returned, handler not found - return error
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Unknown tool: {name}"
            }, indent=2)
        )]
    except ImportError:
        # Handlers module not available - return error
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Handler registry not available. Tool '{name}' cannot be processed."
            }, indent=2)
        )]
    except Exception as e:
        error_msg = f"Error in {name}: {str(e)}\n{traceback.format_exc()}"
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": error_msg
            }, indent=2)
        )]


async def periodic_lock_cleanup(interval_seconds: int = 300):
    """
    Background task that periodically cleans up stale locks.
    Runs every interval_seconds (default: 5 minutes).
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            # Clean up stale locks (older than 60 seconds)
            cleanup_result = cleanup_stale_state_locks(
                project_root=project_root, 
                max_age_seconds=60.0, 
                dry_run=False
            )
            if cleanup_result['cleaned'] > 0:
                print(f"[UNITARES MCP] Periodic cleanup: Removed {cleanup_result['cleaned']} stale lock(s)", file=sys.stderr)
        except asyncio.CancelledError:
            # Task was cancelled, exit gracefully
            break
        except Exception as e:
            # Log error but continue running
            print(f"[UNITARES MCP] Warning: Periodic lock cleanup error: {e}", file=sys.stderr)


async def main():
    """Main entry point for MCP server"""
    # Start background cleanup task
    cleanup_task = asyncio.create_task(periodic_lock_cleanup(interval_seconds=300))
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    finally:
        # Cancel background task when server shuts down
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())

