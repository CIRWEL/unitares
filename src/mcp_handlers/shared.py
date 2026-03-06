"""
Shared context and utilities for MCP handlers.

This module provides access to shared state and functions that handlers need.
All business logic lives in src.agent_state (canonical module).
"""

import sys


class _LazyMCPServer:
    """Lazy proxy to agent_state module. Avoids circular imports."""
    def __getattr__(self, name):
        return getattr(get_mcp_server(), name)


# Singleton instance — import this instead of defining _LazyMCPServer per file
lazy_mcp_server = _LazyMCPServer()


def get_mcp_server():
    """
    Get the agent_state module singleton (canonical business logic module).

    This utility function eliminates the repeated import pattern found across
    multiple handler files. Returns src.agent_state which contains all shared
    state (agent_metadata, monitors, etc.) and business logic.

    Historical note: Previously returned src.mcp_server_std which mixed
    transport code with business logic. Now returns src.agent_state which
    is the clean extraction of just the business logic.

    Returns:
        The agent_state module instance
    """
    if 'src.agent_state' in sys.modules:
        return sys.modules['src.agent_state']
    import src.agent_state as agent_state
    return agent_state
