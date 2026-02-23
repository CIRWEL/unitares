"""
Shared context and utilities for MCP handlers.

This module provides access to shared state and functions that handlers need.
"""

import sys

# Import shared state from mcp_server_std
# These will be set when handlers are imported
monitors = None
agent_metadata = None
lock_manager = None
health_checker = None
process_mgr = None
project_root = None
CURRENT_PID = None
PSUTIL_AVAILABLE = None
MAX_KEEP_PROCESSES = None
PID_FILE = None
SERVER_VERSION = None
SERVER_BUILD_DATE = None

# Helper functions that handlers need
get_or_create_monitor = None
get_agent_or_error = None
require_agent_auth = None
generate_api_key = None
get_or_create_metadata = None
load_monitor_state = None
check_agent_id_default = None
build_standardized_agent_info = None
analyze_agent_patterns = None

def initialize_context(context_dict: dict):
    """Initialize shared context from mcp_server_std"""
    global monitors, agent_metadata, lock_manager, health_checker, process_mgr
    global project_root, CURRENT_PID, PSUTIL_AVAILABLE, MAX_KEEP_PROCESSES
    global PID_FILE, SERVER_VERSION, SERVER_BUILD_DATE
    global get_or_create_monitor, get_agent_or_error, require_agent_auth
    global generate_api_key, get_or_create_metadata
    global load_monitor_state, check_agent_id_default, build_standardized_agent_info
    global analyze_agent_patterns
    
    monitors = context_dict.get('monitors')
    agent_metadata = context_dict.get('agent_metadata')
    lock_manager = context_dict.get('lock_manager')
    health_checker = context_dict.get('health_checker')
    process_mgr = context_dict.get('process_mgr')
    project_root = context_dict.get('project_root')
    CURRENT_PID = context_dict.get('CURRENT_PID')
    PSUTIL_AVAILABLE = context_dict.get('PSUTIL_AVAILABLE')
    MAX_KEEP_PROCESSES = context_dict.get('MAX_KEEP_PROCESSES')
    PID_FILE = context_dict.get('PID_FILE')
    SERVER_VERSION = context_dict.get('SERVER_VERSION')
    SERVER_BUILD_DATE = context_dict.get('SERVER_BUILD_DATE')
    
    get_or_create_monitor = context_dict.get('get_or_create_monitor')
    get_agent_or_error = context_dict.get('get_agent_or_error')
    require_agent_auth = context_dict.get('require_agent_auth')
    generate_api_key = context_dict.get('generate_api_key')
    get_or_create_metadata = context_dict.get('get_or_create_metadata')
    load_monitor_state = context_dict.get('load_monitor_state')
    check_agent_id_default = context_dict.get('check_agent_id_default')
    build_standardized_agent_info = context_dict.get('build_standardized_agent_info')
    analyze_agent_patterns = context_dict.get('analyze_agent_patterns')


def get_mcp_server():
    """
    Get mcp_server_std module singleton.
    
    This utility function eliminates the repeated import pattern found across
    multiple handler files. Use this instead of:
    
        if 'src.mcp_server_std' in sys.modules:
            mcp_server = sys.modules['src.mcp_server_std']
        else:
            import src.mcp_server_std as mcp_server
    
    Returns:
        The mcp_server_std module instance
    """
    if 'src.mcp_server_std' in sys.modules:
        return sys.modules['src.mcp_server_std']
    import src.mcp_server_std as mcp_server
    return mcp_server

