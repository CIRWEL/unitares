#!/usr/bin/env python3
"""
UNITARES Governance MCP Server v1.0 - Standard MCP Protocol Implementation

This is a proper MCP server implementation that follows the Model Context Protocol specification.
It can be used with Cursor, Claude Desktop, and other MCP-compatible clients.

Usage:
    python src/mcp_server_std.py

Configuration:
    Add to Cursor MCP config or Claude Desktop MCP config
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
from dataclasses import dataclass, asdict
from datetime import datetime
import os

# Server version - increment when making breaking changes or critical fixes
SERVER_VERSION = "1.0.3"  # Added state locking, health thresholds, and process heartbeat
SERVER_BUILD_DATE = "2025-11-18"

# PID file for process tracking
PID_FILE = Path(project_root) / "data" / ".mcp_server.pid"
LOCK_FILE = Path(project_root) / "data" / ".mcp_server.lock"

# Maximum number of processes to keep before cleanup
# Increase this if you have many active MCP clients
# Increased to 36 for VC demo (was 9)
MAX_KEEP_PROCESSES = 36

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

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.lifecycle_events is None:
            self.lifecycle_events = []

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


def load_metadata() -> None:
    """Load agent metadata from file"""
    global agent_metadata
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r') as f:
                data = json.load(f)
                agent_metadata = {
                    agent_id: AgentMetadata(**meta)
                    for agent_id, meta in data.items()
                }
        except Exception as e:
            print(f"Warning: Could not load metadata: {e}", file=sys.stderr)


def save_metadata() -> None:
    """Save agent metadata to file"""
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, 'w') as f:
        # Sort by agent_id for consistent file output
        data = {
            agent_id: meta.to_dict()
            for agent_id, meta in sorted(agent_metadata.items())
        }
        json.dump(data, f, indent=2)


def get_or_create_metadata(agent_id: str) -> AgentMetadata:
    """Get metadata for agent, creating if needed"""
    if agent_id not in agent_metadata:
        now = datetime.now().isoformat()
        metadata = AgentMetadata(
            agent_id=agent_id,
            status="active",
            created_at=now,
            last_update=now
        )
        # Add creation lifecycle event
        metadata.add_lifecycle_event("created")

        # Special handling for default agent
        if agent_id == "default_agent":
            metadata.tags.append("pioneer")
            metadata.notes = "First agent - pioneer of the governance system"

        agent_metadata[agent_id] = metadata
        save_metadata()
    return agent_metadata[agent_id]


# Load metadata on startup
load_metadata()


def cleanup_stale_processes():
    """Clean up stale MCP server processes on startup"""
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
                        current_processes.append({
                            'pid': pid,
                            'create_time': proc.info.get('create_time', 0)
                        })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by creation time (oldest first)
        current_processes.sort(key=lambda x: x['create_time'])
        
        # Keep the most recent processes (likely active connections)
        # Only clean up if we exceed the threshold
        if len(current_processes) > MAX_KEEP_PROCESSES:
            stale_count = len(current_processes) - MAX_KEEP_PROCESSES
            print(f"[UNITARES MCP] Found {len(current_processes)} server processes, cleaning up {stale_count} stale ones (keeping {MAX_KEEP_PROCESSES} most recent)...", file=sys.stderr)
            
            for proc_info in current_processes[:-MAX_KEEP_PROCESSES]:  # All except last MAX_KEEP_PROCESSES
                try:
                    proc = psutil.Process(proc_info['pid'])
                    age_seconds = time.time() - proc_info['create_time']
                    age_minutes = int(age_seconds / 60)
                    print(f"[UNITARES MCP] Killing stale process PID {proc_info['pid']} (age: {age_minutes}m)", file=sys.stderr)
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

# Clean up stale processes on startup (using ProcessManager)
try:
    cleaned = process_mgr.cleanup_zombies(max_keep_processes=MAX_KEEP_PROCESSES)
    if cleaned:
        print(f"[UNITARES MCP] Cleaned up {len(cleaned)} zombie processes on startup", file=sys.stderr)
except Exception as e:
    print(f"[UNITARES MCP] Warning: Could not clean zombies on startup: {e}", file=sys.stderr)

# Also run legacy cleanup for compatibility
cleanup_stale_processes()

# Write PID file
write_pid_file()


def get_or_create_monitor(agent_id: str) -> UNITARESMonitor:
    """Get existing monitor or create new one with metadata"""
    # Ensure metadata exists
    get_or_create_metadata(agent_id)

    # Create monitor if needed
    if agent_id not in monitors:
        monitors[agent_id] = UNITARESMonitor(agent_id)

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


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available MCP tools"""
    return [
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
                        "description": "Unique identifier for the agent (e.g., 'cursor_ide', 'claude_code_cli')"
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
                    }
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
                        "description": "Agent identifier"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="get_system_history",
            description="Export complete governance history for an agent. Returns time series data of all governance metrics.",
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
                        "description": "Output format",
                        "default": "json"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="export_to_file",
            description="Export governance history to a file in the server's data directory. Saves timestamped files for analysis and archival. Returns the file path.",
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
            description="List all agents currently being monitored with lifecycle metadata and health status.",
            inputSchema={
                "type": "object",
                "properties": {}
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
            name="pause_agent",
            description="Temporarily pause an agent. Preserves state but blocks new updates until resumed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to pause"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for pausing (optional)"
                    }
                },
                "required": ["agent_id"]
            }
        ),
        Tool(
            name="resume_agent",
            description="Resume a paused or archived agent, returning it to active status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent identifier to resume"
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
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> Sequence[TextContent]:
    """Handle tool calls from MCP client"""
    if arguments is None:
        arguments = {}
    
    try:
        if name == "get_server_info":
            # Get all MCP server processes
            server_processes = []
            
            if not PSUTIL_AVAILABLE:
                server_processes = [{"error": "psutil not available - cannot enumerate processes"}]
            else:
                try:
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'status']):
                        try:
                            cmdline = proc.info.get('cmdline', [])
                            if cmdline and any('mcp_server_std.py' in str(arg) for arg in cmdline):
                                pid = proc.info['pid']
                                create_time = proc.info.get('create_time', 0)
                                uptime_seconds = time.time() - create_time
                                uptime_minutes = int(uptime_seconds / 60)
                                uptime_hours = int(uptime_minutes / 60)
                                
                                server_processes.append({
                                    "pid": pid,
                                    "is_current": pid == CURRENT_PID,
                                    "uptime_seconds": int(uptime_seconds),
                                    "uptime_formatted": f"{uptime_hours}h {uptime_minutes % 60}m",
                                    "status": proc.info.get('status', 'unknown')
                                })
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except Exception as e:
                    server_processes = [{"error": f"Could not enumerate processes: {e}"}]
            
            # Calculate current process uptime
            if PSUTIL_AVAILABLE:
                try:
                    current_proc = psutil.Process(CURRENT_PID)
                    current_uptime = time.time() - current_proc.create_time()
                except:
                    current_uptime = 0
            else:
                current_uptime = 0
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "server_version": SERVER_VERSION,
                    "build_date": SERVER_BUILD_DATE,
                    "current_pid": CURRENT_PID,
                    "current_uptime_seconds": int(current_uptime),
                    "current_uptime_formatted": f"{int(current_uptime / 3600)}h {int((current_uptime % 3600) / 60)}m",
                    "total_server_processes": len(server_processes),
                    "server_processes": server_processes,
                    "pid_file_exists": PID_FILE.exists(),
                    "max_keep_processes": MAX_KEEP_PROCESSES,
                    "health": "healthy" if len(server_processes) <= MAX_KEEP_PROCESSES else "degraded"
                }, indent=2)
            )]
        
        elif name == "process_agent_update":
            agent_id = arguments.get("agent_id", "default_agent")

            # Check agent status
            status_error = check_agent_status(agent_id)
            if status_error:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": status_error
                    }, indent=2)
                )]

            # Check for default agent_id warning
            warning = check_agent_id_default(agent_id)

            # Clean up zombies before processing
            try:
                cleaned = process_mgr.cleanup_zombies(max_keep_processes=MAX_KEEP_PROCESSES)
                if cleaned:
                    print(f"[UNITARES MCP] Cleaned up {len(cleaned)} zombie processes", file=sys.stderr)
            except Exception as e:
                print(f"[UNITARES MCP] Warning: Could not clean zombies: {e}", file=sys.stderr)

            # Acquire lock for agent state update (prevents race conditions)
            try:
                with lock_manager.acquire_agent_lock(agent_id, timeout=5.0):
                    # Get or create monitor
                    monitor = get_or_create_monitor(agent_id)

                    # Prepare agent state
                    import numpy as np
                    agent_state = {
                        "parameters": np.array(arguments.get("parameters", [])),
                        "ethical_drift": np.array(arguments.get("ethical_drift", [0.0, 0.0, 0.0])),
                        "response_text": arguments.get("response_text", ""),
                        "complexity": arguments.get("complexity", 0.5)
                    }

                    # Process update
                    result = monitor.process_update(agent_state)

                    # Update metadata
                    meta = agent_metadata[agent_id]
                    meta.last_update = datetime.now().isoformat()
                    meta.total_updates += 1
                    save_metadata()

                    # Update heartbeat
                    process_mgr.write_heartbeat()

                    # Calculate health status using risk-based thresholds
                    risk_score = result.get('metrics', {}).get('risk_score', None)
                    coherence = result.get('metrics', {}).get('coherence', None)
                    void_active = result.get('metrics', {}).get('void_active', False)
                    
                    health_status, health_message = health_checker.get_health_status(
                        risk_score=risk_score,
                        coherence=coherence,
                        void_active=void_active
                    )
                    
                    # Add health status to response
                    if 'metrics' not in result:
                        result['metrics'] = {}
                    result['metrics']['health_status'] = health_status.value
                    result['metrics']['health_message'] = health_message

                    # Add warning to response if applicable
                    response = {
                        "success": True,
                        **result
                    }
                    if warning:
                        response["warning"] = warning

                    return [TextContent(
                        type="text",
                        text=json.dumps(response, indent=2)
                    )]
            except TimeoutError as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Failed to acquire lock for agent '{agent_id}': {str(e)}. Another process may be updating it."
                    }, indent=2)
                )]
        
        elif name == "get_governance_metrics":
            agent_id = arguments.get("agent_id", "default_agent")

            # Validate agent exists
            monitor, error = get_agent_or_error(agent_id)
            if error:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": error
                    }, indent=2)
                )]

            metrics = monitor.get_metrics()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    **metrics
                }, indent=2)
            )]
        
        elif name == "get_system_history":
            agent_id = arguments.get("agent_id", "default_agent")
            format_type = arguments.get("format", "json")

            # Validate agent exists
            monitor, error = get_agent_or_error(agent_id)
            if error:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": error
                    }, indent=2)
                )]

            history = monitor.export_history(format=format_type)

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "format": format_type,
                    "history": history
                }, indent=2)
            )]
        
        elif name == "export_to_file":
            agent_id = arguments.get("agent_id", "default_agent")
            format_type = arguments.get("format", "json")
            custom_filename = arguments.get("filename")

            # Validate agent exists
            monitor, error = get_agent_or_error(agent_id)
            if error:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": error
                    }, indent=2)
                )]

            # Get history data
            history_data = monitor.export_history(format=format_type)

            # Determine filename
            if custom_filename:
                filename = f"{custom_filename}.{format_type}"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{agent_id}_history_{timestamp}.{format_type}"

            # Ensure data directory exists
            data_dir = Path(project_root) / "data"
            data_dir.mkdir(exist_ok=True)
            
            # Write file
            file_path = data_dir / filename
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(history_data)
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": True,
                        "message": f"History exported successfully",
                        "file_path": str(file_path),
                        "filename": filename,
                        "format": format_type,
                        "agent_id": agent_id,
                        "file_size_bytes": file_path.stat().st_size
                    }, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Failed to write file: {str(e)}",
                        "file_path": str(file_path)
                }, indent=2)
            )]
        
        elif name == "reset_monitor":
            agent_id = arguments.get("agent_id", "default_agent")
            
            if agent_id in monitors:
                del monitors[agent_id]
                message = f"Monitor reset for agent: {agent_id}"
            else:
                message = f"No monitor existed for agent: {agent_id}"
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": message
                }, indent=2)
            )]
        
        elif name == "list_agents":
            # Build rich metadata for each agent
            # Iterate over shared metadata (not just in-memory monitors) to show all agents
            # This fixes the issue where each process only sees agents it has initialized
            agents_list = []
            
            # Get all agents from shared metadata file (not just this process's monitors)
            for agent_id, meta in sorted(agent_metadata.items()):
                try:
                    # Check if this agent has an in-memory monitor in this process
                    monitor = monitors.get(agent_id)
                    
                    if monitor:
                        # Agent is loaded in this process - include full metrics
                        try:
                            state = monitor.state

                            # Determine health status using risk-based thresholds
                            risk_score = getattr(state, 'risk_score', None)
                            health_status_obj, health_message = health_checker.get_health_status(
                                risk_score=risk_score,
                                coherence=state.coherence,
                                void_active=state.void_active
                            )
                            health_status = health_status_obj.value

                            agent_info = {
                                "agent_id": agent_id,
                                "lifecycle_status": meta.status,
                                "health_status": health_status,
                                "created": monitor.created_at.isoformat(),
                                "last_update": monitor.last_update.isoformat(),
                                "update_count": int(state.update_count),
                                "total_updates": meta.total_updates,
                                "version": meta.version,
                                "tags": meta.tags,
                                "notes": meta.notes,
                                "metrics": {
                                    "lambda1": float(state.lambda1),
                                    "coherence": float(state.coherence),
                                    "void_active": bool(state.void_active),
                                    "E": float(state.E),
                                    "I": float(state.I),
                                    "S": float(state.S),
                                    "V": float(state.V)
                                },
                                "loaded_in_process": True  # Indicates monitor is in memory
                            }
                        except Exception as e:
                            # Monitor exists but state access failed
                            print(f"[UNITARES MCP] Error accessing state for agent {agent_id}: {e}", file=sys.stderr)
                            agent_info = {
                                "agent_id": agent_id,
                                "lifecycle_status": meta.status,
                                "health_status": "error",
                                "created": meta.created_at,
                                "last_update": meta.last_update,
                                "total_updates": meta.total_updates,
                                "version": meta.version,
                                "tags": meta.tags,
                                "notes": meta.notes,
                                "error": str(e),
                                "loaded_in_process": True
                            }
                    else:
                        # Agent exists in metadata but not loaded in this process
                        # Show metadata-only info (no live metrics)
                        agent_info = {
                            "agent_id": agent_id,
                            "lifecycle_status": meta.status,
                            "health_status": "unknown",  # Can't calculate without monitor state
                            "created": meta.created_at,
                            "last_update": meta.last_update,
                            "total_updates": meta.total_updates,
                            "version": meta.version,
                            "tags": meta.tags,
                            "notes": meta.notes,
                            "loaded_in_process": False,  # Monitor not in this process's memory
                            "note": "Agent exists in metadata but monitor not loaded in this process. Call process_agent_update to load it."
                        }
                    
                    agents_list.append(agent_info)
                except Exception as e:
                    # Skip agents with errors but log them
                    print(f"[UNITARES MCP] Error processing agent {agent_id} in list_agents: {e}", file=sys.stderr)
                    # Still include basic info for problematic agents
                    agents_list.append({
                        "agent_id": agent_id,
                        "lifecycle_status": meta.status if meta else "unknown",
                        "health_status": "error",
                        "error": str(e)
                    })

            # Summary statistics
            summary = {
                "total_agents": len(agents_list),
                "active": sum(1 for a in agents_list if a["lifecycle_status"] == "active"),
                "paused": sum(1 for a in agents_list if a["lifecycle_status"] == "paused"),
                "archived": sum(1 for a in agents_list if a["lifecycle_status"] == "archived"),
                "healthy": sum(1 for a in agents_list if a["health_status"] == "healthy"),
                "degraded": sum(1 for a in agents_list if a["health_status"] == "degraded"),
                "critical": sum(1 for a in agents_list if a["health_status"] == "critical")
            }

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "agents": agents_list,
                    "summary": summary
                }, indent=2)
            )]

        elif name == "delete_agent":
            agent_id = arguments.get("agent_id")
            confirm = arguments.get("confirm", False)
            backup_first = arguments.get("backup_first", True)

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            if not confirm:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "Set 'confirm: true' to delete agent",
                        "warning": f"This will delete agent '{agent_id}' and move its data to archive/"
                    }, indent=2)
                )]

            # Special protection for default/pioneer agent
            meta = agent_metadata.get(agent_id)
            if meta and "pioneer" in meta.tags:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Cannot delete pioneer agent '{agent_id}'. This agent has historical significance."
                    }, indent=2)
                )]

            # Check if agent exists
            if agent_id not in monitors and agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' does not exist"
                    }, indent=2)
                )]

            # Archive data file if it exists and backup requested
            archive_path = None
            if backup_first:
                data_file = Path(project_root) / "data" / f"{agent_id}.json"
                if data_file.exists():
                    archive_dir = Path(project_root) / "data" / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    archive_path = archive_dir / f"{agent_id}_{timestamp}.json"
                    data_file.rename(archive_path)

            # Remove from monitors
            if agent_id in monitors:
                del monitors[agent_id]

            # Update metadata to deleted status
            if agent_id in agent_metadata:
                agent_metadata[agent_id].status = "deleted"
                save_metadata()

            response = {
                "success": True,
                "message": f"Agent '{agent_id}' deleted",
                "agent_id": agent_id
            }
            if archive_path:
                response["archived_to"] = str(archive_path)

            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2)
            )]

        elif name == "get_agent_metadata":
            agent_id = arguments.get("agent_id")

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            # Check if agent exists
            if agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' not found"
                    }, indent=2)
                )]

            meta = agent_metadata[agent_id]
            monitor = monitors.get(agent_id)

            # Build metadata response
            metadata_response = {
                "success": True,
                **meta.to_dict()
            }

            # Add computed fields
            if monitor:
                metadata_response["current_state"] = {
                    "lambda1": float(monitor.state.lambda1),
                    "coherence": float(monitor.state.coherence),
                    "void_active": bool(monitor.state.void_active),
                    "E": float(monitor.state.E),
                    "I": float(monitor.state.I),
                    "S": float(monitor.state.S),
                    "V": float(monitor.state.V)
                }

            # Days since update
            last_update_dt = datetime.fromisoformat(meta.last_update)
            days_since = (datetime.now() - last_update_dt).days
            metadata_response["days_since_update"] = days_since

            return [TextContent(
                type="text",
                text=json.dumps(metadata_response, indent=2)
            )]

        elif name == "archive_agent":
            agent_id = arguments.get("agent_id")
            reason = arguments.get("reason", "")
            keep_in_memory = arguments.get("keep_in_memory", False)

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            # Check if agent exists
            if agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' not found"
                    }, indent=2)
                )]

            meta = agent_metadata[agent_id]

            # Update metadata
            meta.status = "archived"
            meta.archived_at = datetime.now().isoformat()
            meta.add_lifecycle_event("archived", reason)

            # Unload from memory unless keep_in_memory
            if not keep_in_memory and agent_id in monitors:
                del monitors[agent_id]

            save_metadata()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": f"Agent '{agent_id}' archived",
                    "agent_id": agent_id,
                    "archived_at": meta.archived_at,
                    "kept_in_memory": keep_in_memory
                }, indent=2)
            )]

        elif name == "pause_agent":
            agent_id = arguments.get("agent_id")
            reason = arguments.get("reason", "")

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            if agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' not found"
                    }, indent=2)
                )]

            meta = agent_metadata[agent_id]
            meta.status = "paused"
            meta.paused_at = datetime.now().isoformat()
            meta.add_lifecycle_event("paused", reason)
            save_metadata()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": f"Agent '{agent_id}' paused",
                    "agent_id": agent_id,
                    "paused_at": meta.paused_at
                }, indent=2)
            )]

        elif name == "resume_agent":
            agent_id = arguments.get("agent_id")

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            if agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' not found"
                    }, indent=2)
                )]

            meta = agent_metadata[agent_id]

            if meta.status not in ["paused", "archived"]:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' is {meta.status}, not paused or archived"
                    }, indent=2)
                )]

            meta.status = "active"
            meta.paused_at = None
            meta.archived_at = None
            meta.add_lifecycle_event("resumed")
            save_metadata()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": f"Agent '{agent_id}' resumed",
                    "agent_id": agent_id
                }, indent=2)
            )]

        elif name == "update_agent_metadata":
            agent_id = arguments.get("agent_id")
            tags = arguments.get("tags")
            notes = arguments.get("notes")
            append_notes = arguments.get("append_notes", False)

            if not agent_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": "agent_id is required"
                    }, indent=2)
                )]

            if agent_id not in agent_metadata:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"Agent '{agent_id}' not found"
                    }, indent=2)
                )]

            meta = agent_metadata[agent_id]

            # Update tags (replace)
            if tags is not None:
                meta.tags = tags

            # Update notes (replace or append)
            if notes is not None:
                if append_notes:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    meta.notes = f"{meta.notes}\n[{timestamp}] {notes}".strip()
                else:
                    meta.notes = notes

            save_metadata()

            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "message": f"Metadata updated for agent '{agent_id}'",
                    "agent_id": agent_id,
                    "tags": meta.tags,
                    "notes": meta.notes
                }, indent=2)
            )]

        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Unknown tool: {name}"
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


async def main():
    """Main entry point for MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

