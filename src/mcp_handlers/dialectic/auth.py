"""Shared dialectic authorization helpers.

Centralizes identity resolution and optional session-ownership enforcement for
dialectic submit handlers so authorization policy is defined in one place.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from ..utils import error_response, require_registered_agent
from src.mcp_handlers.shared import lazy_mcp_server as mcp_server


async def resolve_dialectic_agent_id(
    arguments: Dict[str, Any],
    *,
    enforce_session_ownership: bool = False,
) -> Tuple[Optional[str], Optional[Sequence[Any]]]:
    """
    Resolve caller identity for dialectic submit tools.

    - No `agent_id`: use `require_registered_agent` (bound/session identity).
    - With `agent_id`: verify registration and optionally enforce ownership.
    """
    provided = arguments.get("agent_id")
    if isinstance(provided, str):
        provided = provided.strip()

    if not provided:
        agent_id, error = require_registered_agent(arguments)
        if error:
            return None, [error]
        return agent_id, None

    if provided in mcp_server.agent_metadata:
        pass
    else:
        try:
            from ..identity.handlers import _agent_exists_in_postgres

            if not await _agent_exists_in_postgres(provided):
                return None, [error_response(
                    f"Agent '{provided[:8]}...' is not registered",
                    recovery={
                        "action": "Third-party synthesizers must be registered. Call onboard() or identity() first.",
                        "related_tools": ["onboard", "identity"],
                    },
                )]
        except Exception:
            return None, [error_response(
                f"Could not verify agent '{provided[:8]}...' registration",
                recovery={
                    "action": "Retry or call identity() to confirm your current binding.",
                    "related_tools": ["identity", "onboard"],
                },
            )]

    if enforce_session_ownership:
        try:
            from ..context import get_context_agent_id
            from ..utils import verify_agent_ownership

            bound_uuid = get_context_agent_id()
            if bound_uuid and not verify_agent_ownership(provided, arguments):
                return None, [error_response(
                    "agent_id override is not allowed for this call. Use your bound identity.",
                    error_code="AUTH_REQUIRED",
                    error_category="auth_error",
                    recovery={
                        "action": "Remove agent_id and retry, or bind to the reviewer identity first.",
                        "related_tools": ["identity", "bind_session"],
                    },
                )]
        except Exception:
            return None, [error_response(
                "Could not verify session ownership for provided agent_id",
                error_code="AUTH_REQUIRED",
                error_category="auth_error",
                recovery={
                    "action": "Retry without agent_id override or re-bind session identity.",
                    "related_tools": ["identity", "bind_session"],
                },
            )]

    return provided, None
