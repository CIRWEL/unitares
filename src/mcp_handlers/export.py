"""
Export tool handlers.
"""

from typing import Dict, Any, Sequence
from mcp.types import TextContent
import sys
import os
from datetime import datetime
from .utils import success_response, error_response, require_agent_id
from src.governance_monitor import UNITARESMonitor

# Import from mcp_server_std module
if 'src.mcp_server_std' in sys.modules:
    mcp_server = sys.modules['src.mcp_server_std']
else:
    import src.mcp_server_std as mcp_server


async def handle_get_system_history(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle get_system_history tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    format_type = arguments.get("format", "json")
    
    # Try to get from loaded monitor first
    monitor = mcp_server.monitors.get(agent_id)
    if monitor is None:
        # Try to load from disk if not in memory
        persisted_state = mcp_server.load_monitor_state(agent_id)
        if persisted_state is None:
            return [error_response(
                f"Agent '{agent_id}' not found. No history available. Call process_agent_update first to initialize."
            )]
        # Create temporary monitor for export
        monitor = UNITARESMonitor(agent_id, load_state=False)
        monitor.state = persisted_state
    
    history = monitor.export_history(format=format_type)
    
    return success_response({
        "format": format_type,
        "history": history
    })


async def handle_export_to_file(arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """Handle export_to_file tool"""
    agent_id, error = require_agent_id(arguments)
    if error:
        return [error]
    
    format_type = arguments.get("format", "json")
    custom_filename = arguments.get("filename")
    
    # Try to get from loaded monitor first
    monitor = mcp_server.monitors.get(agent_id)
    if monitor is None:
        # Try to load from disk if not in memory
        persisted_state = mcp_server.load_monitor_state(agent_id)
        if persisted_state is None:
            return [error_response(
                f"Agent '{agent_id}' not found. No history available. Call process_agent_update first to initialize."
            )]
        # Create temporary monitor for export
        monitor = UNITARESMonitor(agent_id, load_state=False)
        monitor.state = persisted_state
    
    # Get history data
    history_data = monitor.export_history(format=format_type)
    
    # Determine filename
    if custom_filename:
        filename = f"{custom_filename}.{format_type}"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{agent_id}_history_{timestamp}.{format_type}"
    
    # Ensure data directory exists
    # Use os.path to avoid Path scope issues
    data_dir = os.path.join(mcp_server.project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    # Write file
    file_path = os.path.join(data_dir, filename)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(history_data)
        
        # Get file size
        file_size = os.path.getsize(file_path)
        
        return success_response({
            "message": "History exported successfully",
            "file_path": file_path,
            "filename": filename,
            "format": format_type,
            "agent_id": agent_id,
            "file_size_bytes": file_size
        })
    except Exception as e:
        return [error_response(f"Failed to write file: {str(e)}", {"file_path": str(file_path)})]
