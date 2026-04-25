"""Step 7: Rate limiting and loop detection."""

import time
from collections import defaultdict, deque
from typing import Any, Dict

from src.logging_utils import get_logger
from src.rate_limiter import get_rate_limiter
from ..utils import error_response
from ..error_helpers import rate_limit_error

logger = get_logger(__name__)

# Persistent state for expensive-read-only loop detection
_tool_call_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))


async def check_rate_limit(name: str, arguments: Dict[str, Any], ctx) -> Any:
    """Rate limiting for non-read-only tools + loop detection for expensive reads."""

    # Loop detection for expensive read-only tools
    expensive_read_only_tools = {'list_agents'}
    if name in expensive_read_only_tools:
        now = time.time()
        tool_history = _tool_call_history[name]

        # Clean up old calls (keep last 60 seconds)
        cutoff = now - 60
        while tool_history and tool_history[0] < cutoff:
            tool_history.popleft()
        if not tool_history:
            del _tool_call_history[name]

        if len(tool_history) >= 20:
            return [error_response(
                f"Tool call loop detected: '{name}' called {len(tool_history)} times globally in the last 60 seconds. "
                f"This may indicate a stuck agent. Please wait 30 seconds before retrying.",
                recovery={
                    "action": "Wait 30 seconds before retrying this tool",
                    "related_tools": ["health_check", "get_governance_metrics"],
                    "workflow": "1. Wait 30 seconds 2. Check agent health 3. Retry if needed"
                },
                context={
                    "tool_name": name,
                    "calls_in_last_minute": len(tool_history),
                    "note": "Global rate limit (list_agents doesn't have agent_id parameter)"
                }
            )]

        _tool_call_history[name].append(now)

    # General rate limiting (skip for read-only tools)
    read_only_tools = {'health_check', 'get_server_info', 'list_tools', 'get_thresholds', 'search_knowledge_graph', 'get_governance_metrics', 'skills'}
    if name not in read_only_tools:
        agent_id = arguments.get('agent_id') or 'anonymous'
        rate_limiter = get_rate_limiter()
        allowed, error_msg = rate_limiter.check_rate_limit(agent_id)

        if not allowed:
            return rate_limit_error(agent_id, rate_limiter.get_stats(agent_id))

    return name, arguments, ctx
